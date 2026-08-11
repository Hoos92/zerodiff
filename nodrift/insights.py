"""`nodrift insights` — the self-improvement loop.

Mines your own verification artifacts (nodrift-report.json and
.nodrift/history.jsonl) and turns them into concrete next actions:
config to add, adapters to register, habits to adopt. Everything is
computed locally; nothing leaves the machine.
"""

import json
import os
from typing import Any, Dict, List

from .enterprise import HISTORY_DIR, HISTORY_FILE


def generate(report: Dict[str, Any],
             history: List[Dict[str, Any]]) -> List[str]:
    suggestions = []
    summary = report.get("summary", {})
    divergences = report.get("divergences", [])

    if summary.get("weak_matches"):
        suggestions.append(
            "%d comparisons were fingerprint-only (values NoDrift could "
            "not fully serialize). Register adapters for those types "
            "(nodrift.register_adapter) to turn weak comparisons into "
            "full verification." % summary["weak_matches"])
    if summary.get("skipped_unreplayable"):
        suggestions.append(
            "%d recorded calls were skipped because their inputs cannot "
            "be reconstructed. Prefer boundaries that take plain data "
            "(dicts/strings/numbers), or register adapters for the input "
            "types." % summary["skipped_unreplayable"])
    if summary.get("python_version_mismatch"):
        suggestions.append(
            "Traces were recorded on Python %s but replayed on %s -- "
            "replay on the recording interpreter to rule out "
            "interpreter-caused divergences."
            % ("/".join(summary.get("recorded_python", [])),
               summary.get("replay_python")))

    float_diffs = [d for d in divergences
                   if isinstance(d.get("expected"), float)
                   and isinstance(d.get("actual"), float)]
    if len(float_diffs) >= 3:
        deltas = [abs(d["expected"] - d["actual"]) for d in float_diffs]
        if max(deltas) < 0.01:
            suggestions.append(
                "%d divergences are float differences under 0.01 (max "
                "%.2g). If this is numeric noise rather than behavior, "
                "set float_tolerance in [scrub] -- if it's real rounding "
                "behavior, the rewrite must reproduce it."
                % (len(float_diffs), max(deltas)))

    message_only = [d for d in divergences
                    if d.get("path") == "output.exception.message"]
    if message_only:
        suggestions.append(
            "%d divergences are exception-MESSAGE changes with matching "
            "types. Callers often match on messages; make the rewrite "
            "reproduce the original wording exactly." % len(message_only))

    mutations = [d for d in divergences
                 if str(d.get("path", "")).startswith("mutation.")]
    if mutations:
        suggestions.append(
            "%d divergences are in-place argument mutations -- the "
            "original modifies its arguments and the rewrite must too. "
            "These never show up in return values; check the mutation "
            "paths in the report." % len(mutations))

    boundaries = summary.get("boundaries", {})
    no_error_paths = [b for b, s in boundaries.items()
                      if s.get("replayed", 0) >= 5
                      and s.get("recorded_exceptions", 0) == 0][:3]
    if no_error_paths:
        suggestions.append(
            "No exception-path behaviors recorded for: %s. Drive invalid "
            "inputs in your scenario script -- error behavior is the part "
            "rewrites break most." % ", ".join(no_error_paths))
    hot = sorted(((b, s["diverged"]) for b, s in boundaries.items()
                  if s.get("diverged")), key=lambda x: -x[1])[:3]
    if hot:
        suggestions.append(
            "Divergences concentrate in: %s. Fix these boundaries first."
            % ", ".join("%s (%d)" % pair for pair in hot))

    if history:
        recent = history[-5:]
        verdicts = [entry.get("verdict") for entry in recent]
        if len(recent) >= 3 and all(v == "matched" for v in verdicts):
            suggestions.append(
                "Last %d runs all matched -- lock it in: add "
                "nodrift.testing.verify_traces() to your test suite, gate "
                "PRs with the GitHub Action, and sign the state with "
                "`nodrift attest`." % len(recent))
        elif len(recent) >= 2 and verdicts[-1] != "matched" and \
                verdicts[-2] == "matched":
            suggestions.append(
                "This run regressed a previously matching state -- "
                "compare against the last green run in "
                ".nodrift/history.jsonl (git commits are recorded there).")

    if not suggestions:
        suggestions.append(
            "Verification looks healthy. Habits that keep it that way: "
            "run replay with --history to build a trend, emit "
            "--junit-out for CI, and attest releases so the evidence is "
            "tamper-proof.")
    return suggestions


def cmd_insights(report_path: str, history_dir: str = ".",
                 as_json: bool = False) -> int:
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            report = json.load(f)
    except FileNotFoundError:
        print("nodrift insights: no report found at %s -- run "
              "`nodrift replay` first" % report_path)
        return 2
    history = []
    history_path = os.path.join(history_dir, HISTORY_DIR, HISTORY_FILE)
    if os.path.exists(history_path):
        with open(history_path, "r", encoding="utf-8") as f:
            history = [json.loads(line) for line in f if line.strip()]

    suggestions = generate(report, history)
    if as_json:
        print(json.dumps({"verdict": report.get("verdict"),
                          "suggestions": suggestions}, indent=2))
        return 0
    print("nodrift insights (%s: %d/%d matched):"
          % (report.get("verdict"), report["summary"]["matched"],
             report["summary"]["replayed"]))
    for index, suggestion in enumerate(suggestions, 1):
        print("  %d. %s" % (index, suggestion))
    return 0
