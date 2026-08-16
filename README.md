# ZeroDiff

[![ci](https://github.com/Hoos92/zerodiff/actions/workflows/ci.yml/badge.svg)](https://github.com/Hoos92/zerodiff/actions/workflows/ci.yml)

**Prove your rewrite behaves like the original — before you trust it.**

AI agents can rewrite and migrate legacy code cheaply. The blocker is trust:
the original has years of undocumented behavior baked in, and nobody wants to
deploy a rewrite on an agent's word. ZeroDiff closes that gap with recorded
evidence:

1. **Record** — run the legacy code under real or driver traffic and capture
   every call at chosen function boundaries: inputs, outputs, and exceptions.
2. **Replay** — run the same recorded inputs against the rewritten code
   (written by any agent, or any human — ZeroDiff doesn't care).
3. **Report** — get every behavioral divergence as a machine-readable report
   with actionable hints an agent can fix in a loop, plus a human-readable
   summary. Exit codes make it a CI gate with zero glue.

```
$ zerodiff record -o traces -- python driver.py
  recorded 1,204 calls across 3 boundaries -> traces/

$ zerodiff replay -t traces --map "billing:billing_v2"
  replayed 1,204 recorded behaviors
  matched  1,198   diverged 6   -> zerodiff-report.json, zerodiff-report.md
  exit code 1
```

## Quick start

```bash
pip install zerodiff
# (or, from a checkout: pip install -e .)
zerodiff demo    # 30-second guided example: record a legacy function,
                # catch the silent change a rewrite introduced
zerodiff init    # scaffold zerodiff.toml + .gitignore for your project
```

Examples below are written for bash; in PowerShell, join the `\`-continued
lines into a single line (or swap `\` for a backtick).

Gate it in your existing test suite with one line:

```python
from zerodiff.testing import verify_traces

def test_rewrite_matches_recorded_behavior():
    verify_traces()   # raises AssertionError with a divergence digest
```

CI systems that speak JUnit get first-class output too:
`zerodiff replay -t traces --junit-out zerodiff-junit.xml`.

Record with **zero source edits** — `--include` auto-instruments every
public function of matching modules as they load:

```bash
zerodiff record --include billing -o traces -- python run_legacy_scenarios.py
zerodiff replay -t traces --map "billing:billing_v2"
```

Or mark boundaries explicitly when you want tighter control:

```python
import zerodiff

@zerodiff.record                      # option A: decorate
def calc_price(order): ...

zerodiff.wrap("billing.pricing", "calc_price")   # option B: wrap from outside
```

Replaying an untrusted rewrite? `--isolate` runs every call in a worker
subprocess: a rewrite that crashes the interpreter, calls `os._exit`, or
hangs becomes a reported `process_crash` divergence instead of taking the
harness down:

```bash
zerodiff replay -t traces --isolate --timeout 10
```

## Agent-native workflows

ZeroDiff is vendor-neutral: it verifies code, not agents. Two doors into
the same loop — **bring your own agent CLI, or just bring an API key**:

```bash
# door 1: BYO agent (Claude Code, Codex, Cursor CLI, your own script)
zerodiff migrate ... --agent "claude -p --permission-mode acceptEdits"

# door 2: built-in agent -- you pick the LLM, ZeroDiff does the rest
zerodiff migrate ... --llm anthropic:claude-sonnet-5      # ANTHROPIC_API_KEY
zerodiff migrate ... --llm openai:gpt-5                    # OPENAI_API_KEY
zerodiff migrate ... --llm openai-compatible:llama3.3 \
    --llm-base-url http://localhost:11434/v1              # Ollama/OpenRouter/vLLM

zerodiff llm-check --llm anthropic:claude-sonnet-5   # validate key+model in 2s
zerodiff insights    # mine your report + history for concrete next actions

# the upgrade safety net: prove a dependency bump changed nothing
zerodiff guard baseline --include yourpkg -- python driver.py
pip install -U somedependency
zerodiff guard check
```

The built-in agent is deliberately *minimal and least-privilege*: no
shell, no tools, writes restricted to the mapped rewrite files, and its
output still passes the quality gate and replay like anyone else's code.
ZeroDiff itself still contains no model — the verifier stays deterministic.

```bash
# the whole verified migration in one command: record the legacy code,
# scaffold the rewrite, drive YOUR agent until every recorded behavior
# matches, finish with signed evidence
zerodiff migrate --include billing.pricing \
    --driver "python run_scenarios.py" \
    --map billing.pricing:pricing_v2 \
    --agent "claude -p --permission-mode acceptEdits" \
    --attest --key-file team.key

# unattended fix loop with any agent CLI
zerodiff loop -t traces --agent "claude -p --permission-mode acceptEdits"
zerodiff loop -t traces --agent "codex exec --full-auto {prompt_file}"

# MCP server: Claude Code / Codex / Copilot / Cursor call verification natively
claude mcp add zerodiff -- zerodiff mcp
```

There's also a [GitHub Action](integrations/github-action/) that gates PRs
on recorded behavior, and a [Claude Code hook](integrations/claude-code/)
that blocks any edit which breaks it.

Agent-written code is additionally held to a built-in
**security/quality gate** ([docs/SAFE_CODING.md](docs/SAFE_CODING.md)):
the loop will not finish while the rewrite contains eval/exec,
`shell=True`, interpolated SQL, hardcoded secrets, disabled TLS
verification, or unsafe deserialization — behavioral fidelity alone is
not enough. Standalone: `zerodiff quality myfile.py`.

Exit codes: `0` = every recorded behavior matched, `1` = divergences found,
`2` = harness error. `zerodiff-report.json` is designed to be fed straight back
to a coding agent; `zerodiff-report.md` is for humans.

## What ZeroDiff does and does not claim

ZeroDiff is deliberately honest about its guarantees:

- It proves equivalence **over the recorded behaviors only** — never over all
  possible behaviors. A passing report says "matched N of N recorded
  behaviors", not "the systems are identical". Coverage is only as good as
  the traffic you record.
- **Side effects are not intercepted in v1.** A recorded function that writes
  to a database or calls the network will really do so again during replay.
  Record and replay side-effecting code only against disposable environments.
- Objects ZeroDiff can't fully serialize are compared by type + repr digest and
  flagged as *weak comparisons* in the report, so trust is never overstated.
- Traces contain real runtime data, which may be sensitive. The default
  `.gitignore` excludes trace directories; redaction scrubbers are available.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design and
limitation notes.

## Handling noise (timestamps, floats, UUIDs)

Real code is noisy. Configure per-boundary scrubbers in `zerodiff.toml` so
irrelevant differences don't drown real ones:

```toml
[map]
"billing.pricing" = "billing_v2.pricing"

[scrub]
float_tolerance = 1e-9
builtin = ["uuid", "timestamp"]        # scrub UUID/ISO-timestamp strings
redact_fields = ["password", "*.api_token"]   # never written to disk at all

[scrub.boundaries."billing.pricing.make_receipt"]
ignore_fields = ["generated_at", "trace_id"]
```

`redact_fields` is applied **at record time** — redacted values never reach
the trace files, not merely the report.

## Demos

- `examples/legacy_pricing/` — a deliberately gnarly legacy pricing module,
  an equivalent modern rewrite, and a rewrite with five seeded behavioral
  bugs (all caught). Full loop in under a minute.
- `examples/migration_dateutil/` — a **real PyPI package**: the behavior of
  `dateutil.easter` (1,145 recorded behaviors) verified against a clean
  modern rewrite, with zero source edits. ZeroDiff caught the one *class* of
  divergence — 4 exception-message mismatches — that a human review would
  wave through. Write-up with numbers:
  [docs/CASE_STUDY.md](docs/CASE_STUDY.md).
- `examples/validation_*` — ten more real GitHub libraries (`roman`,
  `inflection`, `humanize`, `word2number`, `python-slugify`, `num2words`,
  `python-stdnum`, `semver`, `humanfriendly`, `pytimeparse` — the last
  four through the full `zerodiff migrate` pipeline with signed
  attestations). Program total: **11 libraries, 12,952 recorded
  behaviors, 11/11 clean-room rewrites wrong on first pass, all brought
  to 100%**. Results: [docs/VALIDATION.md](docs/VALIDATION.md).

Questions like "do I need an LLM for this?" (no) are answered in the
[FAQ](docs/FAQ.md).

## Licensing

The core harness is MIT and always will be — record, replay, report, the
quality gate, the agent loop, the MCP server, `guard`, `insights`, the
integrations. Fork it, sell it, do what you like.

One file is not MIT: `zerodiff/enterprise.py`, which provides signed
tamper-evident attestations (`zerodiff attest`) and verification history
(`zerodiff history`). It is source-available — free for evaluation,
development, CI, and research — and requires a commercial license only when
an attestation is relied upon as evidence in the course of business. Terms
in [LICENSE-COMMERCIAL](LICENSE-COMMERCIAL), tiers in
[docs/PRICING.md](docs/PRICING.md), how to get one in
[COMMERCIAL.md](COMMERCIAL.md).

Two example directories (`examples/validation_stdnum/`,
`examples/validation_num2words/`) contain re-implementations derived from
LGPL upstream libraries and are LGPL-licensed; see the `NOTICE` in each. The
tool itself contains no third-party code.

## Status

**v0.15** — Python 3.8+, function-level boundaries, zero runtime
dependencies, 251 tests. `pip install zerodiff`.

The verb set is stable: `record` / `replay` / `report` (0.1–0.2, with
zero-edit `--include` instrumentation and `--isolate` crash-safe replay),
`loop` + `mcp` + the GitHub Action and Claude Code hook (0.3),
`init` / `demo` / `zerodiff.testing` / JUnit output and the Enterprise
attestation + history layer (0.4), `migrate` — the end-to-end verified
migration pipeline (0.5), the security/quality gate (0.7), argument-mutation
and stateful-code support with parallel replay (0.8), the built-in `--llm`
agent (0.9), `insights` (0.10), and `guard` — the dependency-upgrade
safety net (0.11).

0.12 renamed the project from Retrace to ZeroDiff. 0.13 and 0.14 were
correctness audits of the harness itself: 0.13 fixed three cases where the
differ reported a *false match*, and 0.14 fixed cases where a verdict was
reported without the evidence to back it (a zero-behavior replay reading as
a pass, attestations signing failed runs) — see the
[CHANGELOG](CHANGELOG.md).

0.15 renamed the project from NoDrift to ZeroDiff after an unrelated
package claimed the old name on PyPI.

Roadmap: HTTP service-level recording and side-effect interception.

MIT licensed, except `zerodiff/enterprise.py` — see [Licensing](#licensing).
