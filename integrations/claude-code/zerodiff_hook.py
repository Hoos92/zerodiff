#!/usr/bin/env python
"""Claude Code PostToolUse hook: block edits that break recorded behavior.

After every Edit/Write, replays the recorded traces; if any recorded
behavior diverged, exits with code 2 so Claude Code blocks the change and
feeds the divergence digest straight back to the agent as the reason.

Requires a `zerodiff-hook.toml`-adjacent setup: run from the project root,
with a `traces/` directory and a `zerodiff.toml` holding the [map].
"""

import json
import subprocess
import sys


def main() -> int:
    # hook stdin carries the tool-use event; we only need to know an edit
    # happened, so it can be drained without parsing details
    try:
        json.load(sys.stdin)
    except Exception:
        pass

    proc = subprocess.run(
        [sys.executable, "-m", "zerodiff.cli", "replay", "-t", "traces",
         "--isolate"],
        capture_output=True, text=True)
    if proc.returncode == 0:
        return 0
    if proc.returncode == 2:
        # harness/setup error: report but don't block the edit on it
        print("zerodiff hook: harness error:\n" + proc.stderr,
              file=sys.stderr)
        return 0

    # divergence: exit 2 blocks the change and Claude sees this digest
    try:
        with open("zerodiff-report.json", encoding="utf-8") as f:
            report = json.load(f)
        lines = ["This edit breaks recorded behavior "
                 "(%d divergences). Fix these before proceeding:"
                 % report["summary"]["divergence_count"]]
        for d in report["divergences"][:10]:
            lines.append("- [%s] %s at %s: expected %s, got %s. %s"
                         % (d["kind"], d["boundary"], d["path"],
                            str(d["expected"])[:80], str(d["actual"])[:80],
                            d["hint"]))
        print("\n".join(lines), file=sys.stderr)
    except Exception:
        print("zerodiff: recorded behaviors diverged (see "
              "zerodiff-report.md)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
