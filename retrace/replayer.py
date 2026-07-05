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


def resolve_callable(target: str):
    """Resolve 'pkg.mod.func' to (callable, None) or (None, why).

    A module that EXISTS but fails to import (relative imports, syntax
    errors, missing deps) is a completely different failure from a
    missing function -- the reason is surfaced so agents can fix it."""
    parts = target.split(".")
    for split in range(len(parts) - 1, 0, -1):
        module_name = ".".join(parts[:split])
        try:
            obj = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name == module_name:
                continue  # this prefix genuinely doesn't exist; try shorter
            # the module exists but imports something that doesn't
            return None, ("module %r failed to import: %s: %s"
                          % (module_name, type(exc).__name__, exc))
        except Exception as exc:  # module found but broken on import
            return None, ("module %r failed to import: %s: %s"
                          % (module_name, type(exc).__name__, exc))
        try:
            for attr in parts[split:]:
                obj = getattr(obj, attr)
        except AttributeError:
            return None, ("module %r imports fine but has no attribute "
                          "%r" % (module_name,
                                  ".".join(parts[split:])))
        # unwrap if the replacement itself is decorated with @retrace.record
        inner = getattr(obj, "__retrace_wrapped__", None)
        return (inner if inner is not None else obj), None
    return None, "no importable module found for %r" % target


def _encode_args(args, kwargs) -> Dict[str, Any]:
    return {"args": [serializer.encode(a) for a in args],
            "kwargs": {k: serializer.encode(v) for k, v in kwargs.items()}}


def compute_replay_mutations(before: Dict[str, Any], args,
                             kwargs) -> Dict[str, Any]:
    """After the rewrite ran, re-encode its arguments and report which
    ones it modified in place (compared to their pre-call encoding)."""
    after = _encode_args(args, kwargs)
    mutations = {}
    for i, tree in enumerate(after["args"]):
        if serializer.canonical_json(tree) != serializer.canonical_json(
                before["args"][i]):
            mutations[str(i)] = tree
    for key, tree in after["kwargs"].items():
        if serializer.canonical_json(tree) != serializer.canonical_json(
                before["kwargs"][key]):
            mutations["kw:" + key] = tree
    return mutations


class InProcessInvoker:
    """Fast default: imports and calls the rewrite inside this process."""

    def invoke(self, target: str,
               encoded_input: Dict[str, Any]) -> Dict[str, Any]:
        fn, resolve_error = resolve_callable(target)
        if fn is None:
            return {"status": "missing", "detail": resolve_error}
        try:
            args = [serializer.decode(a)
                    for a in encoded_input.get("args", [])]
            kwargs = {k: serializer.decode(v)
                      for k, v in encoded_input.get("kwargs", {}).items()}
        except serializer.OpaqueValueError as exc:
            return {"status": "unreplayable", "reason": str(exc)}
        before = _encode_args(args, kwargs)
        try:
            value = fn(*args, **kwargs)
            outcome = {"status": "ok",
                       "output": {"type": "return",
                                  "value": serializer.encode(value)}}
        except KeyboardInterrupt:
            raise
        except BaseException as exc:  # SystemExit etc. are behavior too
            outcome = {"status": "ok",
                       "output": {"type": "exception",
                                  "exception": {"type": type(exc).__name__,
                                                "message": str(exc)}}}
        try:
            outcome["mutations"] = compute_replay_mutations(before, args,
                                                            kwargs)
        except Exception:
            pass
        return outcome

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
        self.recorded_py = set()  # major.minor versions seen in traces

    def _bstats(self, boundary: str) -> Dict[str, int]:
        return self.boundaries.setdefault(
            boundary, {"replayed": 0, "matched": 0, "diverged": 0,
                       "skipped": 0, "recorded_exceptions": 0})

    def merge(self, other: "ReplayResult") -> None:
        self.divergences.extend(other.divergences)
        self.skipped.extend(other.skipped)
        self.traces_total += other.traces_total
        self.replayed += other.replayed
        self.matched += other.matched
        self.diverged_traces += other.diverged_traces
        self.weak_matches += other.weak_matches
        self.recorded_py |= other.recorded_py
        for boundary, stats in other.boundaries.items():
            mine = self._bstats(boundary)
            for key, value in stats.items():
                mine[key] = mine.get(key, 0) + value

    def to_dict(self) -> Dict[str, Any]:
        replay_py = "{}.{}".format(*sys.version_info[:2])
        mismatch = bool(self.recorded_py and
                        any(v != replay_py for v in self.recorded_py))
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
                "recorded_python": sorted(self.recorded_py),
                "replay_python": replay_py,
                "python_version_mismatch": mismatch,
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
    recorded_py = trace.get("meta", {}).get("py")
    if recorded_py:
        result.recorded_py.add(".".join(recorded_py.split(".")[:2]))

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
        detail = outcome.get("detail") or ""
        result.divergences.append(differ.Divergence(
            differ.KIND_MISSING, target, tid, "boundary", target, new_target,
            "recorded boundary {t} maps to {n}, which does not resolve to "
            "a callable ({d}). The rewrite must be a standalone module: "
            "absolute imports only, no imports from the original "
            "package.".format(t=target, n=new_target, d=detail),
            input_preview=preview))
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

    # in-place argument mutation is behavior; only checked when the trace
    # recorded it (absent field = old trace or opt-out)
    if "mutations" in trace:
        mut_divs, mut_weak = _diff_mutations(
            trace, outcome.get("mutations", {}), plan, target, tid,
            preview)
        divs = divs + mut_divs
        weak += mut_weak

    result.weak_matches += weak
    if divs:
        result.divergences.extend(divs)
        result.diverged_traces += 1
        stats["diverged"] += 1
    else:
        result.matched += 1
        stats["matched"] += 1


def _pre_call_tree(trace: Dict[str, Any], key: str):
    if key.startswith("kw:"):
        return trace["input"]["kwargs"].get(key[3:])
    return trace["input"]["args"][int(key)]


def _diff_mutations(trace: Dict[str, Any], actual_mut: Dict[str, Any],
                    plan: Dict[str, Any], target: str, tid: str,
                    preview: str):
    """Compare recorded vs replayed argument after-states. An argument
    neither side mutated compares pre-call vs pre-call and stays silent."""
    expected_mut = trace["mutations"]
    divs = []
    weak = 0
    for key in sorted(set(expected_mut) | set(actual_mut)):
        pre = _pre_call_tree(trace, key)
        expected_tree = scrubbers.scrub(
            expected_mut.get(key, pre), plan["ignore_fields"],
            plan["regexes"], redact_fields=plan["redact_fields"])
        actual_tree = scrubbers.scrub(
            actual_mut.get(key, pre), plan["ignore_fields"],
            plan["regexes"], redact_fields=plan["redact_fields"])
        label = "mutation.args[%s]" % key[3:] if key.startswith("kw:") \
            else "mutation.args[%s]" % key
        d, w = differ.diff_trees(
            expected_tree, actual_tree, label, boundary=target,
            trace_id=tid, input_preview=preview,
            float_tolerance=plan["float_tolerance"])
        for div in d:
            div.hint = ("the original modified this argument in place "
                        "and the rewrite's after-state differs -- a "
                        "drop-in replacement must mutate its arguments "
                        "identically. " + div.hint)
        divs.extend(d)
        weak += w
    return divs, weak


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


def _replay_traces(traces: List[Dict[str, Any]], mappings: Dict[str, str],
                   cfg: Config, invoker) -> ReplayResult:
    result = ReplayResult()
    result.traces_total = len(traces)
    try:
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


def replay_all(trace_dir: str, mappings: Dict[str, str], cfg: Config,
               isolate: bool = False, timeout: float = DEFAULT_TIMEOUT,
               in_order: bool = False, jobs: int = 1) -> ReplayResult:
    if in_order:
        # stateful code: replay EVERY call chronologically -- identical
        # inputs can legitimately produce different outputs as module
        # state evolves, so deduplication would discard real behavior
        traces = list(store.iter_traces(trace_dir))
        traces.sort(key=lambda t: (t.get("meta", {}).get("ts", ""),
                                   t.get("meta", {}).get("seq", 0)))
    else:
        traces = store.load_unique_traces(trace_dir)

    if jobs <= 1 or len(traces) < 2:
        invoker = SubprocessInvoker(timeout) if isolate \
            else InProcessInvoker()
        return _replay_traces(traces, mappings, cfg, invoker)

    # parallel replay: shard across isolated workers (jobs implies
    # isolation -- sharing one interpreter across threads would let the
    # rewrite's state bleed between shards)
    shards = [traces[i::jobs] for i in range(jobs)]
    results = [None] * len(shards)  # type: List[Optional[ReplayResult]]

    def run_shard(index: int) -> None:
        results[index] = _replay_traces(
            shards[index], mappings, cfg, SubprocessInvoker(timeout))

    threads = [threading.Thread(target=run_shard, args=(i,), daemon=True)
               for i in range(len(shards))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    merged = ReplayResult()
    merged.traces_total = 0
    for shard_result in results:
        if shard_result is not None:
            merged.merge(shard_result)
    return merged
