"""One-line behavioral gating inside any test suite.

    # test_behavior.py
    from nodrift.testing import verify_traces

    def test_rewrite_matches_recorded_behavior():
        verify_traces("traces")

Raises BehaviorMismatch (an AssertionError, so every test runner renders it
natively) with a readable digest of the first divergences.
"""

from typing import Any, Dict, Optional

from . import report as report_mod
from .config import load_config
from .replayer import replay_all

MAX_DIGEST_LINES = 10


class BehaviorMismatch(AssertionError):
    """Raised when replayed behavior diverges from the recording."""

    def __init__(self, report: Dict[str, Any]) -> None:
        self.report = report
        super().__init__(_digest(report))


class NoBehaviorsReplayed(AssertionError):
    """Raised when 0 behaviors were replayed -- a wrong trace_dir, an empty
    directory, or a failed record step must never look like a pass."""

    def __init__(self, trace_dir: str) -> None:
        self.trace_dir = trace_dir
        super().__init__(
            "0 behaviors replayed from %r -- this is not a pass; check "
            "that the directory exists and contains recorded .jsonl "
            "traces." % trace_dir)


def _digest(report: Dict[str, Any]) -> str:
    s = report["summary"]
    lines = ["%d of %d recorded behaviors diverged "
             "(full report: nodrift-report.md)"
             % (s["diverged"], s["replayed"])]
    for d in report["divergences"][:MAX_DIGEST_LINES]:
        lines.append("  [%s] %s at %s (input %s): expected %s, got %s"
                     % (d["kind"], d["boundary"], d["path"],
                        str(d.get("input", ""))[:60],
                        str(d["expected"])[:60], str(d["actual"])[:60]))
    remaining = len(report["divergences"]) - MAX_DIGEST_LINES
    if remaining > 0:
        lines.append("  ... and %d more" % remaining)
    return "\n".join(lines)


def verify_traces(trace_dir: str = "traces",
                  mappings: Optional[Dict[str, str]] = None,
                  config_path: Optional[str] = None,
                  isolate: bool = False,
                  write_reports: bool = True) -> Dict[str, Any]:
    """Replay recorded traces; raise BehaviorMismatch on any divergence.

    Returns the report dict on success so callers can assert on coverage
    (e.g. minimum replayed counts) as well.
    """
    cfg = load_config(config_path)
    merged = cfg.mappings()
    merged.update(mappings or {})
    result = replay_all(trace_dir, merged, cfg, isolate=isolate)
    report = report_mod.build_report(result.to_dict(), trace_dir, merged)
    if write_reports:
        report_mod.write_reports(report)
    if report["verdict"] == "no_data":
        raise NoBehaviorsReplayed(trace_dir)
    if report["summary"]["divergence_count"] > 0:
        raise BehaviorMismatch(report)
    return report
