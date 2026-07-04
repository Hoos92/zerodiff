"""Replay recorded traces against a replacement implementation."""

import importlib
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import differ, scrubbers, serializer, store
from .config import Config


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
                       "skipped": 0})

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
    parts = [differ._preview(a, 60) for a in encoded_input.get("args", [])]
    for key, value in sorted(encoded_input.get("kwargs", {}).items()):
        parts.append("%s=%s" % (key, differ._preview(value, 60)))
    return "(" + ", ".join(parts) + ")"


def replay_one(trace: Dict[str, Any], mappings: Dict[str, str],
               cfg: Config, result: ReplayResult) -> None:
    target = trace["boundary"]["target"]
    tid = trace["id"]
    stats = result._bstats(target)
    preview = _input_preview(trace["input"])

    new_target = map_target(target, mappings)
    fn = resolve_callable(new_target)
    if fn is None:
        stats["diverged"] += 1
        result.diverged_traces += 1
        result.replayed += 1
        stats["replayed"] += 1
        result.divergences.append(differ.Divergence(
            differ.KIND_MISSING, target, tid, "boundary", target, new_target,
            "recorded boundary {t} maps to {n}, which does not resolve to a "
            "callable -- the rewrite is missing this function, or the "
            "[map] entry in retrace.toml is wrong.".format(
                t=target, n=new_target)))
        return

    # decode inputs; opaque inputs cannot be faithfully replayed
    try:
        args = [serializer.decode(a) for a in trace["input"].get("args", [])]
        kwargs = {k: serializer.decode(v)
                  for k, v in trace["input"].get("kwargs", {}).items()}
    except serializer.OpaqueValueError as exc:
        stats["skipped"] += 1
        result.skipped.append({
            "trace_id": tid, "boundary": target,
            "reason": "input contains a value that cannot be reconstructed "
                      "({}); coverage for this call is not verified".format(exc),
        })
        return

    # invoke the replacement; its exceptions are recorded behavior, not errors
    try:
        value = fn(*args, **kwargs)
        actual = {"type": "return", "value": serializer.encode(value)}
    except Exception as exc:  # noqa: BLE001 - any exception is behavior
        actual = {"type": "exception",
                  "exception": {"type": type(exc).__name__,
                                "message": str(exc)}}

    plan = scrubbers.compile_scrubbers(cfg, target)
    expected_scrubbed = _scrub_output(trace["output"], plan)
    actual_scrubbed = _scrub_output(actual, plan)

    divs, weak = differ.diff_output(
        expected_scrubbed, actual_scrubbed, boundary=target, trace_id=tid,
        input_preview=preview, float_tolerance=plan["float_tolerance"])

    result.replayed += 1
    stats["replayed"] += 1
    result.weak_matches += weak
    if divs:
        result.divergences.extend(divs)
        result.diverged_traces += 1
        stats["diverged"] += 1
    else:
        result.matched += 1
        stats["matched"] += 1


def _scrub_output(output: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    if output.get("type") == "return":
        return {"type": "return",
                "value": scrubbers.scrub(output.get("value"),
                                         plan["ignore_fields"],
                                         plan["regexes"])}
    exc = output.get("exception", {})
    scrubbed_msg = scrubbers.scrub(exc.get("message"),
                                   plan["ignore_fields"], plan["regexes"])
    return {"type": "exception",
            "exception": {"type": exc.get("type"), "message": scrubbed_msg}}


def replay_all(trace_dir: str, mappings: Dict[str, str],
               cfg: Config) -> ReplayResult:
    result = ReplayResult()
    traces = store.load_unique_traces(trace_dir)
    result.traces_total = len(traces)
    for trace in traces:
        try:
            replay_one(trace, mappings, cfg, result)
        except Exception as exc:  # harness bug on this trace: report, go on
            target = trace.get("boundary", {}).get("target", "unknown")
            result.replayed += 1
            result.diverged_traces += 1
            result._bstats(target)["replayed"] += 1
            result._bstats(target)["diverged"] += 1
            result.divergences.append(differ.Divergence(
                differ.KIND_REPLAY_ERROR, target, trace.get("id", "?"),
                "harness", None, repr(exc),
                "the harness itself failed while replaying this trace -- "
                "this is a Retrace problem, not evidence about the rewrite; "
                "please report it."))
    return result
