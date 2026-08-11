# NoDrift FAQ

## Do I need an LLM to use NoDrift?

**No.** The core product is fully deterministic — recording, replay,
diffing, and reporting involve no AI, no API keys, no network calls, and
produce identical results on every run. You can use NoDrift exactly like
you use pytest:

- run `nodrift record` / `nodrift replay` by hand or in CI,
- gate merges with the GitHub Action or `nodrift.testing.verify_traces()`,
- read `nodrift-report.md` yourself and fix divergences yourself.

Where an LLM *optionally* enters is on the **fixing** side — when you want
something to write or repair the rewrite for you. NoDrift supports three
levels of that, all vendor-neutral:

1. **You use your own agent, manually.** Ask Claude Code / Cursor /
   Copilot to fix the code and paste or point it at `nodrift-report.json`
   — every divergence carries a hint written for exactly this purpose.
2. **Your agent calls NoDrift natively.** Register the MCP server
   (`claude mcp add nodrift -- nodrift mcp`) and the agent can run
   `nodrift_replay` itself and read the results, mid-task. The Claude Code
   hook variant blocks any edit that breaks recorded behavior.
3. **NoDrift drives the agent, unattended.**
   `nodrift loop -t traces --agent "claude -p --permission-mode acceptEdits"`
   replays, hands every divergence to the agent CLI you name, and repeats
   until 100% or the iteration cap. The `--agent` command is any shell
   command — Claude Code, Codex, Cursor CLI, or a shell script of your own.

NoDrift itself never calls a model. Your traces never leave your machine.

## Which LLM does the agent loop use?

None of its own — you choose, through either door:

- `--agent "<cli command>"`: any external agent (Claude Code, Codex,
  Cursor CLI, a shell script). The model is whatever that agent runs.
- `--llm provider:model`: NoDrift's **built-in minimal agent** calls the
  LLM API directly with *your* key — `anthropic:...`, `openai:...`, or
  `openai-compatible:...` with `--llm-base-url` (Ollama, OpenRouter,
  vLLM, Gemini's compatibility endpoint). No third-party agent install
  needed. Validate a key/model in seconds with `nodrift llm-check`.

Either way the verifier itself stays deterministic and model-free, and
the model choice, permissions, and API costs are entirely yours. The
built-in agent is least-privilege by design: no shell, no tools, and it
can only write the rewrite files under verification.

## What stops the agent from writing insecure code?

Two layers (see [SAFE_CODING.md](SAFE_CODING.md)): every fix prompt
carries explicit secure-coding rules, and a built-in static gate
(zero-dependency AST analysis) blocks the loop while error-severity
findings remain — eval/exec, shell=True, SQL interpolation, hardcoded
secrets, disabled TLS verification, unsafe deserialization, and more. A
rewrite that matches every recorded behavior but uses `eval()` does not
go green.

## Does it work for languages other than Python?

Today, recording and replay are Python-only (the recorder wraps Python
functions). The trace format, differ, reports, agent loop, and MCP server
are already language-neutral. The roadmap's next boundary is HTTP-level
recording — record request/response pairs of a running service — which
works for *any* implementation language behind the endpoint. Per-language
function recorders (JavaScript/TypeScript first) come after.

## Is "100% matched" a proof of correctness?

No, and NoDrift never claims it is. It proves equivalence **over the
recorded behaviors** — the inputs your recording session actually
exercised. That is the point: recorded reality beats intentions, but its
coverage is bounded by your driver. Reports state "matched N of M recorded
behaviors" and list per-boundary counts; anything NoDrift couldn't fully
compare is flagged (`weak_comparison`, `skipped`) rather than silently
counted as a match.

## Is my data safe?

Traces are plain local files and may contain real runtime data. NoDrift
never uploads anything. `nodrift init` gitignores the traces directory by
default; `redact_fields` in `nodrift.toml` strips named fields **at record
time**, so secrets never reach disk at all.

## What kinds of code can I record?

Module-level functions (and class methods via explicit
`nodrift.wrap("mod", "Class.method")`) whose inputs are reasonably
serializable. Side-effecting functions (DB writes, network) can be
recorded, but replaying them performs the side effects again — keep replay
pointed at disposable environments until side-effect interception ships.

## How is this different from my test suite?

Tests encode what someone *believed* the code should do; recordings encode
what it *actually does*, including the quirks nobody wrote down. In our
validation across 11 real libraries (12,952 recorded behaviors), every
single clean-room rewrite passed casual inspection and still diverged from
recorded reality — see [VALIDATION.md](VALIDATION.md). NoDrift complements
tests; it doesn't replace them.
