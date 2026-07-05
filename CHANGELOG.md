# Changelog

## 0.9.1 — 2026-07-05 (live-run fix: original source in fix prompts)

- fix prompts now include the ORIGINAL legacy modules' source as
  read-only reference (located via import machinery, 15KB/module cap).
  Found by live testing with real OpenAI models: without the reference,
  from-scratch scaffolds force the agent to reverse-engineer formulas
  from I/O pairs — gpt-4o-mini plateaued at 15/37 and gpt-4o at 18/37;
  with it, gpt-4o-mini one-shots the same migration (37/37) and a real
  library, pytimeparse (42/42), fully unattended
- recorded behavior remains the ground truth; the source is reference
  material, and it is part of what gets sent to the chosen LLM provider
  (see SECURITY.md)

## 0.9.0 — 2026-07-05 (built-in agent)

- two doors into the loop: `--agent "<cli>"` (BYO, unchanged) or
  `--llm provider:model` — a built-in minimal agent calling your chosen
  LLM directly (anthropic / openai / openai-compatible with
  `--llm-base-url` for Ollama, OpenRouter, vLLM, Gemini-compat); zero
  dependencies (stdlib urllib), keys from standard env vars, `[agent]`
  config in retrace.toml
- the built-in agent is least-privilege by design: no shell, no tools,
  output protocol is full-file sentinel blocks, writes restricted to the
  allowlisted rewrite files (path traversal rejected), and everything it
  writes still passes the quality gate and replay
- `retrace llm-check`: validate key/model/endpoint with one tiny
  round-trip before burning a real run
- 161 tests (stub LLM server, no network in CI)

## 0.8.0 — 2026-07-04 (architecture review)

- **argument mutation is now verified behavior**: recording captures the
  after-state of any argument the original modified in place; a rewrite
  that returns the right value but doesn't mutate identically diverges at
  `mutation.args[N]`. This also fixes a latent recorder bug where inputs
  were encoded *after* the call (a mutating original recorded its mutated
  inputs as the inputs). Opt out with `[record] mutations = false`
- **stateful code support**: `meta.seq` global chronology on every trace;
  `retrace replay --in-order` replays every call (no dedup) in recorded
  order
- **agent-loop economics**: stall detection (identical problems two
  iterations running → stop early), `--agent-timeout` (default 1800s),
  and prompts now name the rewrite files and the attempt number
- **parallel replay**: `--jobs N` shards across isolated workers
  (verified identical counts to serial on 10k behaviors)
- **coherence**: MCP server gained `retrace_quality`; attestations with
  `--code` now embed the quality-gate outcome in the signed body and
  accept `RETRACE_ATTEST_KEY`; reports flag Python-version drift between
  record and replay
- robustness: markdown reports cap at 100 divergences; unreadable files
  become gate findings; `retrace init` template includes `[quality]`

## 0.7.0 — 2026-07-04

- security/quality gate (docs/SAFE_CODING.md): zero-dependency AST
  analysis blocking eval/exec, shell=True, SQL interpolation, hardcoded
  secrets, unsafe deserialization, disabled TLS verification, insecure
  tempfiles; warns on weak hashes, exception-swallowing, mutable
  defaults, and length/complexity/nesting budget violations
- enforced in `retrace loop` / `retrace migrate` by default (findings are
  appended to the agent's fix prompt; the loop won't go green while
  blocking findings remain; `--no-quality` opts out); standalone
  `retrace quality FILE...`; budgets configurable via `[quality]` in
  retrace.toml
- secure-coding rules embedded in every agent fix prompt

## 0.6.0 — 2026-07-04

- `retrace replay` warns loudly when no `[map]` entry applied to any
  boundary (you were replaying the original against itself)
- attestations can pin rewrite source files (`retrace attest --code FILE`)
  and record the git commit; `verify-attestation` checks code digests too
- `retrace history` entries record the git commit
- new complex validation: python-stdnum (luhn/isbn/iban) through the full
  `retrace migrate` pipeline end to end
- repo governance: CHANGELOG, SECURITY.md, CONTRIBUTING.md, CI workflow

## 0.5.0 — 2026-07-04

- `retrace migrate`: the whole verified migration in one command — record
  → scaffold rewrite stubs from recorded boundaries → drive any agent CLI
  through the replay-fix loop → optional signed attestation

## 0.4.0 — 2026-07-04

- free tier: `retrace init`, `retrace demo`, `retrace.testing.verify_traces()`
  pytest one-liner, `retrace replay --junit-out`
- Enterprise (COMMERCIAL.md): `retrace attest` / `verify-attestation`
  (HMAC-signed tamper-evident evidence), `retrace history`

## 0.3.0 — 2026-07-03

- `retrace loop`: unattended replay→agent→replay loop for any agent CLI
- `retrace mcp`: zero-dependency MCP server (Claude Code, Codex, Copilot,
  Cursor)
- GitHub Action and Claude Code hook integrations

## 0.2.0 — 2026-07-03

- `--include` zero-edit auto-instrumentation via import hook
- `--isolate` subprocess replay: crashes/hangs become `process_crash`
  divergences with per-call `--timeout`
- record-time redaction (`redact_fields`)
- real-world case study: dateutil.easter (docs/CASE_STUDY.md)

## 0.1.0 — 2026-07-03

- initial release: record / replay / report, canonical serializer with
  flagged weak comparisons, divergence taxonomy with agent-actionable
  hints, scrubbers, JSONL traces, CI-ready exit codes
