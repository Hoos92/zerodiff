# Retrace + Claude Code

Two ways to wire Retrace into Claude Code, from loosest to strictest.

## 1. MCP server (agent calls verification when it wants)

```bash
claude mcp add retrace -- retrace mcp
```

Claude Code then has two tools: `retrace_replay` (replay traces against the
current code, get divergences with hints) and `retrace_report`. Ask Claude
to "verify the rewrite with retrace" and it can run and read the results
natively. Replay is subprocess-isolated by default, so repeated calls test
the *current* files, not stale imports.

## 2. PostToolUse hook (every edit is gated, no opt-out)

`retrace_hook.py` replays the recorded traces after each Edit/Write. On
divergence it exits with code 2, which blocks the change and feeds the
divergence digest back to Claude as the reason — the agent sees exactly
which recorded behavior it broke and fixes it before moving on.

`.claude/settings.json` in the project:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "python integrations/claude-code/retrace_hook.py"
          }
        ]
      }
    ]
  }
}
```

The hook is deliberately forgiving about harness errors (missing traces
directory, bad config): those are reported but do not block edits — only
real behavioral divergence blocks.

## 3. Unattended loop (Retrace drives the agent)

```bash
retrace loop -t traces --agent "claude -p --permission-mode acceptEdits" --max-iters 5
```

Replay → hand every divergence with hints to the agent → replay again,
until every recorded behavior matches or the iteration cap is hit. Works
with any agent CLI (`--agent "codex exec --full-auto {prompt_file}"`).
