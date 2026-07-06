"""The agent feedback loop: replay -> feed divergences to an agent -> repeat.

Vendor-neutral by design. The agent is any shell command:

    nodrift loop -t traces --agent "claude -p --permission-mode acceptEdits"
    nodrift loop -t traces --agent "codex exec --full-auto {prompt_file}"

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
replaces. A behavioral verification tool (NoDrift) replayed recorded
real-world calls of the original against the rewrite and found divergences.

Rules:
- Fix the REWRITE's source code so each divergence disappears.
- Behavior must match the original exactly, including exception types,
  exception messages, and returned value types -- even where the original's
  behavior looks wrong. Do not "improve" behavior.
- Never modify the traces directory, nodrift.toml, or the report files.
- Do not re-run the verification yourself; the loop does that.

Secure & quality coding rules (statically enforced -- the loop will not
finish while violations remain):
- Never use eval/exec, os.system, or subprocess with shell=True.
- Never deserialize with pickle/marshal or yaml.load without SafeLoader.
- Build SQL only with parameterized queries; never interpolate values.
- No hardcoded secrets or tokens; read them from the environment.
- Never disable TLS certificate verification.
- Catch specific exceptions; never swallow errors with `except: pass`.
- No mutable default arguments.
- Keep functions small and flat (length/complexity/nesting budgets).
- Add no new dependencies and no network or filesystem access the
  original did not have.

Divergences ({count} shown of {total}):
"""

QUALITY_SECTION = """
Security/quality findings in the rewrite ({errors} blocking, {warns} warnings):
"""

PROMPT_ENTRY = """\
{index}. [{kind}] {boundary} at {path}
   input: {input}
   expected: {expected}
   actual: {actual}
   hint: {hint}
"""


def build_prompt(report: Dict, quality_findings=None, files=None,
                 iteration=None, max_iters=None, originals=None) -> str:
    divergences = report["divergences"]
    shown = divergences[:MAX_PROMPT_DIVERGENCES]
    lines = [PROMPT_HEADER.format(count=len(shown), total=len(divergences))]
    if iteration is not None and max_iters is not None:
        lines.insert(0, "This is fix attempt %d of %d.\n"
                     % (iteration, max_iters))
    if files:
        lines.insert(0, "The rewrite source files to fix: %s\n"
                     % ", ".join(files))
    for i, d in enumerate(shown, 1):
        lines.append(PROMPT_ENTRY.format(
            index=i, kind=d["kind"], boundary=d["boundary"], path=d["path"],
            input=str(d.get("input", ""))[:200],
            expected=str(d["expected"])[:200],
            actual=str(d["actual"])[:200],
            hint=d["hint"]))
    if quality_findings:
        from . import quality as quality_mod

        errors = quality_mod.error_count(quality_findings)
        lines.append(QUALITY_SECTION.format(
            errors=errors, warns=len(quality_findings) - errors))
        lines.append(quality_mod.render_text(quality_findings))
    mappings = report.get("mappings") or {}
    if mappings:
        lines.append("The rewrite modules (old -> new): " + ", ".join(
            "%s -> %s" % (k, v) for k, v in sorted(mappings.items())))
    if originals:
        lines.append("\nOriginal legacy source (READ-ONLY reference: "
                     "replicate its behavior exactly, quirks included; "
                     "the recorded behaviors above remain the ground "
                     "truth):")
        for name, text in originals:
            lines.append("--- original module %s ---\n%s\n--- end ---"
                         % (name, text))
    return "\n".join(lines) + "\n"


MAX_ORIGINAL_CHARS = 15000


def original_sources(mappings: Dict[str, str], workdir: str):
    """Locate the ORIGINAL (legacy) modules' source for the fix prompt.
    The recorded behavior stays the ground truth; the source is reference
    material -- without it, a from-scratch rewrite forces the agent to
    reverse-engineer formulas from I/O pairs, which live testing showed
    even strong models cannot do reliably."""
    import importlib.util

    sources = []
    for old_prefix in sorted(mappings):
        try:
            spec = importlib.util.find_spec(old_prefix)
        except Exception:
            continue
        origin = getattr(spec, "origin", None) if spec else None
        if not origin or not os.path.exists(origin):
            continue
        try:
            with open(origin, "r", encoding="utf-8",
                      errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        if len(text) > MAX_ORIGINAL_CHARS:
            text = text[:MAX_ORIGINAL_CHARS] + "\n# ... (truncated)\n"
        sources.append((old_prefix, text))
    return sources


def rewrite_files(mappings: Dict[str, str], workdir: str):
    """Resolve mapped rewrite module prefixes to existing source files."""
    paths = []
    for new_prefix in sorted(set(mappings.values())):
        candidate = os.path.join(workdir,
                                 new_prefix.replace(".", os.sep) + ".py")
        if os.path.exists(candidate):
            paths.append(candidate)
        else:
            package_init = os.path.join(workdir,
                                        new_prefix.replace(".", os.sep),
                                        "__init__.py")
            if os.path.exists(package_init):
                paths.append(package_init)
    return paths


AGENT_TIMED_OUT = -9999


class ShellAgent:
    """The BYO door: any agent CLI, prompt via stdin or {prompt_file}."""

    def __init__(self, agent_cmd: str, agent_timeout: float = 1800.0):
        self.agent_cmd = agent_cmd
        self.agent_timeout = agent_timeout

    def run(self, prompt: str, files, workdir: str) -> int:
        return run_agent(self.agent_cmd, prompt, workdir,
                         agent_timeout=self.agent_timeout)


def run_agent(agent_cmd: str, prompt: str, workdir: str,
              agent_timeout: float = 1800.0) -> int:
    prompt_file = os.path.join(workdir, "nodrift-fix-prompt.md")
    with open(prompt_file, "w", encoding="utf-8", newline="\n") as f:
        f.write(prompt)
    try:
        # the user's --agent value IS a shell command by contract
        if "{prompt_file}" in agent_cmd:
            cmd = agent_cmd.replace("{prompt_file}", prompt_file)
            proc = subprocess.run(cmd, shell=True, cwd=workdir,  # nodrift-quality: ignore[shell-injection]
                                  timeout=agent_timeout)
        else:
            proc = subprocess.run(agent_cmd, shell=True, cwd=workdir,  # nodrift-quality: ignore[shell-injection]
                                  input=prompt.encode("utf-8"),
                                  timeout=agent_timeout)
    except subprocess.TimeoutExpired:
        return AGENT_TIMED_OUT
    return proc.returncode


def _fingerprint(report: Dict, blocking_quality: int) -> str:
    import hashlib

    entries = sorted("%s|%s|%s" % (d["trace_id"], d["path"], d["kind"])
                     for d in report["divergences"])
    payload = "\n".join(entries) + "\n#quality=%d" % blocking_quality
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_loop(trace_dir: str, mappings: Dict[str, str], cfg: Config,
             agent_cmd: str = None, max_iters: int = 5,
             timeout: float = 30.0, workdir: str = ".",
             json_out: str = report_mod.REPORT_JSON,
             md_out: str = report_mod.REPORT_MD,
             quality_gate: bool = True,
             agent_timeout: float = 1800.0,
             runner=None) -> int:
    """Returns the number of blocking problems remaining (0 = success):
    behavioral divergences plus, with the quality gate on (default),
    error-severity security/quality findings in the rewrite files.

    Replays always run isolated: each iteration gets a fresh worker
    process, so the agent's edits are actually re-imported (an in-process
    replay would keep testing the stale module from before the fix)."""
    from . import quality as quality_mod

    if runner is None:
        runner = ShellAgent(agent_cmd, agent_timeout)
    originals = original_sources(mappings, workdir)
    remaining = 0
    recent_fingerprints = []  # detects A-A stalls AND A-B-A-B cycles
    for iteration in range(1, max_iters + 1):
        result = replay_all(trace_dir, mappings, cfg, isolate=True,
                            timeout=timeout)
        report = report_mod.build_report(result.to_dict(), trace_dir,
                                         mappings)
        report_mod.write_reports(report, json_out, md_out)
        divergences = report["summary"]["divergence_count"]

        files = rewrite_files(mappings, workdir)
        findings = []
        if quality_gate:
            findings = quality_mod.check_files(
                files, budgets=cfg.quality_budgets(),
                disabled=cfg.quality_disabled())
        blocking = quality_mod.error_count(findings)
        remaining = divergences + blocking

        print("nodrift loop: iteration %d: %d of %d matched, "
              "%d divergences, %d blocking quality findings"
              % (iteration, report["summary"]["matched"],
                 report["summary"]["replayed"], divergences, blocking))
        if remaining == 0:
            if findings:  # non-blocking warnings still worth surfacing
                print("nodrift loop: quality warnings (non-blocking):")
                print(quality_mod.render_text(findings))
            return 0

        fingerprint = _fingerprint(report, blocking)
        if fingerprint in recent_fingerprints[-3:]:
            print("nodrift loop: agent is stalled or cycling (this exact "
                  "problem set was already seen); stopping early after "
                  "%d iterations to avoid burning agent spend"
                  % iteration)
            break
        recent_fingerprints.append(fingerprint)

        if iteration == max_iters:
            break
        print("nodrift loop: invoking agent...")
        code = runner.run(
            build_prompt(report, findings, files=files,
                         iteration=iteration, max_iters=max_iters,
                         originals=originals),
            files, workdir)
        if code == AGENT_TIMED_OUT:
            print("nodrift loop: agent timed out after %ds; stopping"
                  % agent_timeout)
            break
        if code != 0:
            print("nodrift loop: warning: agent exited with code %d" % code)
    return remaining
