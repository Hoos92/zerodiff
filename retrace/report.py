"""Render replay results as retrace-report.json (agents) and .md (humans).

Product invariant: reports state "matched N of M recorded behaviors" and
never claim unqualified equivalence. Weak matches and skipped traces are
always surfaced, never folded into "matched".
"""

import datetime
import json
from typing import Any, Dict

REPORT_JSON = "retrace-report.json"
REPORT_MD = "retrace-report.md"


def build_report(result_dict: Dict[str, Any], trace_dir: str,
                 mappings: Dict[str, str]) -> Dict[str, Any]:
    return {
        "retrace_report": 1,
        "generated_at": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "trace_dir": trace_dir,
        "mappings": mappings,
        "summary": result_dict["summary"],
        "verdict": _verdict(result_dict["summary"]),
        "divergences": result_dict["divergences"],
        "skipped": result_dict["skipped"],
        "note": "Equivalence is verified over recorded behaviors only; "
                "coverage is bounded by the traffic that was recorded.",
    }


def _verdict(summary: Dict[str, Any]) -> str:
    if summary["divergence_count"] > 0:
        return "diverged"
    if summary["skipped_unreplayable"] > 0 or summary["weak_matches"] > 0:
        return "matched_with_gaps"
    return "matched"


def write_reports(report: Dict[str, Any], json_path: str = REPORT_JSON,
                  md_path: str = REPORT_MD) -> None:
    with open(json_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, indent=2, sort_keys=False, ensure_ascii=True)
        f.write("\n")
    with open(md_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(render_markdown(report))


def render_markdown(report: Dict[str, Any]) -> str:
    s = report["summary"]
    lines = []
    lines.append("# Retrace report")
    lines.append("")
    lines.append("**Result: {} of {} replayed behaviors matched.**".format(
        s["matched"], s["replayed"]))
    lines.append("")
    lines.append("| | count |")
    lines.append("|---|---|")
    lines.append("| recorded behaviors (unique) | {} |".format(
        s["traces_total"]))
    lines.append("| replayed | {} |".format(s["replayed"]))
    lines.append("| matched | {} |".format(s["matched"]))
    lines.append("| diverged | {} |".format(s["diverged"]))
    lines.append("| skipped (unreplayable input) | {} |".format(
        s["skipped_unreplayable"]))
    lines.append("| weak comparisons (matched by fingerprint only) | {} |"
                 .format(s["weak_matches"]))
    lines.append("")
    lines.append("Coverage note: {}".format(report["note"]))
    lines.append("")

    lines.append("## Boundaries")
    lines.append("")
    lines.append("| boundary | replayed | matched | diverged | skipped "
                 "| recorded exception behaviors |")
    lines.append("|---|---|---|---|---|---|")
    for target in sorted(s["boundaries"]):
        b = s["boundaries"][target]
        lines.append("| `{}` | {} | {} | {} | {} | {} |".format(
            target, b["replayed"], b["matched"], b["diverged"], b["skipped"],
            b.get("recorded_exceptions", 0)))
    lines.append("")

    if report["divergences"]:
        kinds = {}
        for d in report["divergences"]:
            kinds[d["kind"]] = kinds.get(d["kind"], 0) + 1
        lines.append("## Divergences ({})".format(len(report["divergences"])))
        lines.append("")
        lines.append("| kind | count |")
        lines.append("|---|---|")
        for kind in sorted(kinds):
            lines.append("| {} | {} |".format(kind, kinds[kind]))
        lines.append("")

        by_boundary = {}
        for d in report["divergences"]:
            by_boundary.setdefault(d["boundary"], []).append(d)
        for boundary in sorted(by_boundary):
            group = by_boundary[boundary]
            lines.append("### `{}` ({} divergences)".format(boundary,
                                                            len(group)))
            lines.append("")
            for i, d in enumerate(group, 1):
                lines.append("{}. **{}** at `{}`".format(i, d["kind"],
                                                         d["path"]))
                if d.get("input"):
                    lines.append("   - input: `{}`".format(
                        _md_code_safe(d["input"])))
                lines.append("   - expected: `{}`".format(
                    _md_code_safe(d["expected"])))
                lines.append("   - actual: `{}`".format(
                    _md_code_safe(d["actual"])))
                lines.append("   - hint: {}".format(d["hint"]))
                lines.append("   - trace: `{}`".format(d["trace_id"]))
                lines.append("")

    if report["skipped"]:
        lines.append("## Skipped traces ({})".format(len(report["skipped"])))
        lines.append("")
        for skip in report["skipped"]:
            lines.append("- `{}` ({}): {}".format(
                skip["trace_id"], skip["boundary"], skip["reason"]))
        lines.append("")

    return "\n".join(lines) + "\n"


def _md_code_safe(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(
        value, ensure_ascii=True, sort_keys=True, default=str)
    text = text.replace("`", "'")
    return text if len(text) <= 200 else text[:200] + "..."
