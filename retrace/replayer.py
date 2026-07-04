"""Replay recorded traces against a replacement implementation.

Replay runs through an *invoker*: in-process by default (fast), or an
isolated worker subprocess (``--isolate``) that survives rewrites which
crash, call os._exit, or hang — those become reported behavior instead of
taking the harness down.
"""

import importlib
import json
import os
import queue
import subprocess
import sys
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import differ, scrubbers, serializer, store
from .config import Config

DEFAULT_TIMEOUT = 30.0


def map_target(target: str, mappings: Dict[str, str]) -> str:
    """Apply the longest-prefix old→new mapping to a boundary target."""
    best_old = None
    for old in mappings:
        if (target == old or target.startswith(old + ".")) and \
                (best_old is None or len(old) > len(best_old)):
            best_old = old
    if best_old is None:
        return target
    return mappings[best_old] + target[len(best_old):]


def resolve_callable(target: str) -> Optional[Callable]:
    """Resolve 'pkg.mod.func' or 'pkg.mod.Class.method' to a callable.

    Tries the longest importable module prefix, then walks attributes."""
    parts = target.split(".")
    for split in range(len(parts) - 1, 0, -1):
        module_name = ".".join(parts[:split])
        try:
            obj = importlib.import_module(module_name)
        except ImportError:
            continue
        try:
            for attr in parts[split:]:
                obj = getattr(obj, attr)
        except AttributeError:
            return None
        # unwrap if the replacement itself is decorated with @retrace.record
        inner = getattr(obj, "__retrace_wrapped__", None)
        return inner if inner is not None else obj
    return None


class InProcessInvoker:
    """Fast default: imports and calls the rewrite inside this process."""

    def invoke(self, target: str,
               encoded_input: Dict[str, Any]) -> Dict[str, Any]:
        fn = resolve_callable(target)
        if fn is None:
            return {"status": "missing"}
        try:
            args = [serializer.decode(a)
                    for a in encoded_input.get("args", [])]
            kwargs = {k: serializer.decode(v)
                      for k, v in encoded_input.get("kwargs", {}).items()}
        except serializer.OpaqueValueError as exc:
            return {"status": "unreplayable", "reason": str(exc)}
        try:
            value = fn(*args, **kwargs)
            return {"status": "ok",
                    "output": {"type": "return",
                               "value": serializer.encode(value)}}
        except KeyboardInterrupt:
            raise
        except BaseException as exc:  # SystemExit etc. are behavior too
            return {"status": "ok",
                    "output": {"type": "exception",
                               "exception": {"type": type(exc).__name__,
                                             "message": str(exc)}}}

    def close(self) -> None:
        pass


class SubprocessInvoker:
    """Replays each call in a worker subprocess (see retrace.worker).

    A worker that dies or hangs is reported as a `process_crash` divergence
    and a fresh worker is started for the next trace.
    """

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout
        self._proc = None  # type: Optional[subprocess.Popen]
        self._queue = None  # type: Optional[queue.Queue]

    def _reader(self, stream, out_queue) -> None:
        for line in stream:
            out_queue.put(line)
        out_queue.put(None)  # EOF marker

    def _start(self) -> bool:
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "retrace.worker"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1)
        self._queue = queue.Queue()
        thread = threading.Thread(
            target=self._reader, args=(self._proc.stdout, self._queue),
            daemon=True)
        thread.start()
        try:
            ready = self._queue.get(timeout=self.timeout)
        except queue.Empty:
            self._kill()
            return False
        return ready is not None and \
            json.loads(ready).get("status") == "ready"

    def _ensure(self) -> bool:
        if self._proc is not None and self._proc.poll() is None:
            return True
        return self._start()

    def _kill(self) -> Optional[int]:
        code = None
        if self._proc is not None:
            try:
                self._proc.kill()
                code = self._proc.wait(timeout=5)
            except Exception:
                pass
        self._proc = None
        self._queue = None
        return code

    def invoke(self, target: str,
               encoded_input: Dict[str, Any]) -> Dict[str, Any]:
        if not self._ensure():
            return {"status": "error",
                    "error": "could not start replay worker"}
        try:
            self._proc.stdin.write(json.dumps(
                {"target": target, "input": encoded_input},
                ensure_ascii=True) + "\n")
            self._proc.stdin.flush()
        except OSError:
            code = self._proc.poll()
            self._kill()
            return {"status": "crash", "exit_code": code}
        try:
            line = self._queue.get(timeout=self.timeout)
        except queue.Empty:
            self._kill()
            return {"status": "hang", "timeout": self.timeout}
        if line is None:  # worker died mid-call
            code = self._proc.wait()
            self._kill()
            return {"status": "crash", "exit_code": code}
        return json.loads(line)

    def close(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.stdin.write('{"op": "exit"}\n')
                self._proc.stdin.flush()
                self._proc.wait(timeout=5)
            except Exception:
                pass
        self._kill()


class ReplayResult:
    def __init__(self) -> None:
        self.divergences = []  # type: List[differ.Divergence]
        self.skipped = []  # type: List[Dict[str, Any]]
        self.boundaries = {}  # type: Dict[str, Dict[str, int]]
        self.traces_total = 0
        self.replayed = 0
        self.matched = 0
        self.diverged_traces = 0
        self.weak_matches = 0

    def _bstats(self, boundary: str) -> Dict[str, int]:
        return self.boundaries.setdefault(
            boundary, {"replayed": 0, "matched": 0, "diverged": 0,
                       "skipped": 0, "recorded_exceptions": 0})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": {
                "traces_total": self.traces_total,
                "replayed": self.replayed,
                "matched": self.matched,
                "diverged": self.diverged_traces,
                "skipped_unreplayable": len(self.skipped),
                "weak_matches": self.weak_matches,
                "divergence_count": len(self.divergences),
                "boundaries": self.boundaries,
            },
            "divergences": [d.to_dict() for d in self.divergences],
            "skipped": self.skipped,
        }


def _input_preview(encoded_input: Dict[str, Any]) -> str:
    parts = [differ._preview(a, 100) for a in encoded_input.get("args", [])]
    for key, value in sorted(encoded_input.get("kwargs", {}).items()):
        parts.append("%s=%s" % (key, differ._preview(value, 100)))
    return "(" + ", ".join(parts) + ")"


def replay_one(trace: Dict[str, Any], mappings: Dict[str, str],
               cfg: Config, result: ReplayResult,
               invoker: Optional[InProcessInvoker] = None) -> None:
    if invoker is None:
        invoker = InProcessInvoker()
    target = trace["boundary"]["target"]
    tid = trace["id"]
    stats = result._bstats(target)
    preview = _input_preview(trace["input"])
    if trace["output"].get("type") == "exception":
        stats["recorded_exceptions"] += 1

    new_target = map_target(target, mappings)
    outcome = invoker.invoke(new_target, trace["input"])
    status = outcome.get("status")

    if status == "unreplayable":
        stats["skipped"] += 1
        result.skipped.append({
            "trace_id": tid, "boundary": target,
            "reason": "input contains a value that cannot be reconstructed "
                      "({}); coverage for this call is not verified".format(
                          outcome.get("reason")),
        })
        return

    result.replayed += 1
    stats["replayed"] += 1

    if status == "missing":
        stats["diverged"] += 1
        result.diverged_traces += 1
        result.divergences.append(differ.Divergence(
            differ.KIND_MISSING, target, tid, "boundary", target, new_target,
            "recorded boundary {t} maps to {n}, which does not resolve to a "
            "callable -- the rewrite is missing this function, or the "
            "[map] entry in retrace.toml is wrong.".format(
                t=target, n=new_target), input_preview=preview))
        return

    if status in ("crash", "hang"):
        stats["diverged"] += 1
        result.diverged_traces += 1
        if status == "crash":
            hint = ("replaying input {inp} killed the worker process "
                    "(exit code {c}) -- the rewrite terminates the "
                    "interpreter (os._exit, abort, or a native crash) where "
                    "the original completed normally; remove the "
                    "process-level exit from {n}.".format(
                        inp=preview, c=outcome.get("exit_code"), n=new_target))
            actual = "process exited with code {}".format(
                outcome.get("exit_code"))
        else:
            hint = ("replaying input {inp} did not finish within {t}s -- "
                    "the rewrite hangs (infinite loop or blocking call) "
                    "where the original returned; fix the non-termination "
                    "in {n} or raise --timeout.".format(
                        inp=preview, t=outcome.get("timeout"), n=new_target))
            actual = "no response within {}s".format(outcome.get("timeout"))
        result.divergences.append(differ.Divergence(
            differ.KIND_CRASH, target, tid, "process",
            "completed with recorded output", actual, hint,
            input_preview=preview))
        return

    if status == "error":
        stats["diverged"] += 1
        result.diverged_traces += 1
        result.divergences.append(differ.Divergence(
            differ.KIND_REPLAY_ERROR, target, tid, "harness", None,
            outcome.get("error"),
            "the harness itself failed while replaying this trace -- this "
            "is a Retrace problem, not evidence about the rewrite; please "
            "report it.", input_preview=preview))
        return

    plan = scrubbers.compile_scrubbers(cfg, target)
    expected_scrubbed = _scrub_output(trace["output"], plan)
    actual_scrubbed = _scrub_output(outcome["output"], plan)

    divs, weak = differ.diff_output(
        expected_scrubbed, actual_scrubbed, boundary=target, trace_id=tid,
        input_preview=preview, float_tolerance=plan["float_tolerance"])

    result.weak_matches += weak
    if divs:
        result.divergences.extend(divs)
        result.diverged_traces += 1
        stats["diverged"] += 1
    else:
        result.matched += 1
        stats["matched"] += 1


def _scrub_output(output: Dict[str, Any],
                  plan: Dict[str, Any]) -> Dict[str, Any]:
    if output.get("type") == "return":
        return {"type": "return",
                "value": scrubbers.scrub(output.get("value"),
                                         plan["ignore_fields"],
                                         plan["regexes"],
                                         redact_fields=plan["redact_fields"])}
    exc = output.get("exception", {})
    scrubbed_msg = scrubbers.scrub(exc.get("message"),
                                   plan["ignore_fields"], plan["regexes"],
                                   redact_fields=plan["redact_fields"])
    return {"type": "exception",
            "exception": {"type": exc.get("type"), "message": scrubbed_msg}}


def replay_all(trace_dir: str, mappings: Dict[str, str], cfg: Config,
               isolate: bool = False,
               timeout: float = DEFAULT_TIMEOUT) -> ReplayResult:
    result = ReplayResult()
    invoker = SubprocessInvoker(timeout) if isolate else InProcessInvoker()
    try:
        traces = store.load_unique_traces(trace_dir)
        result.traces_total = len(traces)
        for trace in traces:
            try:
                replay_one(trace, mappings, cfg, result, invoker)
            except Exception as exc:  # harness bug on this trace: report it
                target = trace.get("boundary", {}).get("target", "unknown")
                result.replayed += 1
                result.diverged_traces += 1
                result._bstats(target)["replayed"] += 1
                result._bstats(target)["diverged"] += 1
                result.divergences.append(differ.Divergence(
                    differ.KIND_REPLAY_ERROR, target, trace.get("id", "?"),
                    "harness", None, repr(exc),
                    "the harness itself failed while replaying this trace "
                    "-- this is a Retrace problem, not evidence about the "
                    "rewrite; please report it."))
    finally:
        invoker.close()
    return result
