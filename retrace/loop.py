"""The agent feedback loop: replay -> feed divergences to an agent -> repeat.

Vendor-neutral by design. The agent is any shell command:

    retrace loop -t traces --agent "claude -p --permission-mode acceptEdits"
    retrace loop -t traces --agent "codex exec --full-auto {prompt_file}"

If the command contains ``{prompt_file}``, the path of a file holding the
fix prompt is substituted; otherwise the prompt is piped to the agent's
stdin. The loop replays, hands the agent every divergence with its hint,
and repeats until every recorded behavior matches or --max-iters is hit.
"""

import os
import subprocess
from typing import Dict

from . import report as report_mod
from .config import Config
from .replayer import replay_all

MAX_PROMPT_DIVERGENCES = 40

PROMPT_HEADER = """\
You are fixing a rewrite so it behaves exactly like the original code it
replaces. A behavioral verification tool (Retrace) replayed recorded
real-world calls of the original against the rewrite and found divergences.

Rules:
- Fix the REWRITE's source code so each divergence disappears.
- Behavior must match the original exactly, including exception types,
  exception messages, and returned value types -- even where the original's
  behavior looks wrong. Do not "improve" behavior.
- Never modify the traces directory, retrace.toml, or the report files.
- Do not re-run the verification yourself; the loop does that.

Divergences ({count} shown of {total}):
"""

PROMPT_ENTRY = """\
{index}. [{kind}] {boundary} at {path}
   input: {input}
   expected: {expected}
   actual: {actual}
   hint: {hint}
"""


def build_prompt(report: Dict) -> str:
    divergences = report["divergences"]
    shown = divergences[:MAX_PROMPT_DIVERGENCES]
    lines = [PROMPT_HEADER.format(count=len(shown), total=len(divergences))]
    for i, d in enumerate(shown, 1):
        lines.append(PROMPT_ENTRY.format(
            index=i, kind=d["kind"], boundary=d["boundary"], path=d["path"],
            input=str(d.get("input", ""))[:200],
            expected=str(d["expected"])[:200],
            actual=str(d["actual"])[:200],
            hint=d["hint"]))
    mappings = report.get("mappings") or {}
    if mappings:
        lines.append("The rewrite modules (old -> new): " + ", ".join(
            "%s -> %s" % (k, v) for k, v in sorted(mappings.items())))
    return "\n".join(lines) + "\n"


def run_agent(agent_cmd: str, prompt: str, workdir: str) -> int:
    prompt_file = os.path.join(workdir, "retrace-fix-prompt.md")
    with open(prompt_file, "w", encoding="utf-8", newline="\n") as f:
        f.write(prompt)
    if "{prompt_file}" in agent_cmd:
        cmd = agent_cmd.replace("{prompt_file}", prompt_file)
        proc = subprocess.run(cmd, shell=True, cwd=workdir)
    else:
        proc = subprocess.run(agent_cmd, shell=True, cwd=workdir,
                              input=prompt.encode("utf-8"))
    return proc.returncode


def run_loop(trace_dir: str, mappings: Dict[str, str], cfg: Config,
             agent_cmd: str, max_iters: int = 5,
             timeout: float = 30.0, workdir: str = ".",
             json_out: str = report_mod.REPORT_JSON,
             md_out: str = report_mod.REPORT_MD) -> int:
    """Returns the number of divergences remaining (0 = success).

    Replays always run isolated: each iteration gets a fresh worker
    process, so the agent's edits are actually re-imported (an in-process
    replay would keep testing the stale module from before the fix)."""
    for iteration in range(1, max_iters + 1):
        result = replay_all(trace_dir, mappings, cfg, isolate=True,
                            timeout=timeout)
        report = report_mod.build_report(result.to_dict(), trace_dir,
                                         mappings)
        report_mod.write_reports(report, json_out, md_out)
        remaining = report["summary"]["divergence_count"]
        print("retrace loop: iteration %d: %d of %d matched, %d divergences"
              % (iteration, report["summary"]["matched"],
                 report["summary"]["replayed"], remaining))
        if remaining == 0:
            return 0
        if iteration == max_iters:
            break
        print("retrace loop: invoking agent...")
        code = run_agent(agent_cmd, build_prompt(report), workdir)
        if code != 0:
            print("retrace loop: warning: agent exited with code %d" % code)
    return remaining
