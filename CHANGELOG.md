# Changelog


## 0.15.0 — 2026-08-15 (rename: NoDrift -> ZeroDiff)

The product is now **ZeroDiff** (package `zerodiff`, CLI `zerodiff`,
config `zerodiff.toml`, env vars `ZERODIFF_*`, reports
`zerodiff-report.*`, attestations `zerodiff-attestation.json`, history in
`.zerodiff/`).

Why: while this project was still private, an unrelated developer
published a package named `nodrift` to PyPI on 2026-08-07 — independently,
and for a strikingly similar purpose ("prove a refactor changed nothing by
running it"). Two people reached for the same obvious phrase for the same
idea. The PyPI name was theirs first, `pip install nodrift` would have
installed a different tool, and a shared name with a same-category project
helps nobody. **ZeroDiff** says the same thing — a green run means zero
diff between the original's recorded behavior and the rewrite's — and it
is ours alone.

- no behavior changes: the rename is mechanical, and the full suite,
  the dogfooded quality gate, every validation cohort, and the
  seeded-bug counter-check all pass identically before and after
- the agent file-block protocol sentinel is now
  `<<<ZERODIFF-FILE: name.py>>>` / `<<<ZERODIFF-END>>>`
- inline quality suppressions are now `# zerodiff-quality: ignore[rule]`
- if you used NoDrift: rename the package in imports, rename
  `nodrift.toml` to `zerodiff.toml`, and re-point `NODRIFT_*` env vars.
  **Recorded traces need no migration** — the trace format is unchanged
  and the tool name in `meta` is written but never read back. Verified
  concretely: the `examples/validation_roman` traces still carry
  `"retrace": "0.7.0"` from two renames ago and replay 10,083/10,083
  clean under this release.

## 0.14.0 — 2026-08-10 (trust audit: "pass" verdicts that weren't)

A second, independent audit pass over the modules v0.13.0 didn't cover
found two ways ZeroDiff could report a clean pass without having verified
anything, plus a silent config failure. Same defect class as v0.13.0's
false matches, one layer up: not "compared wrong" but "claimed a verdict
it hadn't earned."

Fixed — verdicts that weren't:

- **Zero replayed behaviors reported `matched`.** An empty or wrong
  `--traces` path, a CI artifact that failed to restore, or a `record`
  step that silently captured nothing all produced "matched 0, diverged
  0" and **exit 0** — a clean pass backed by no evidence at all. This
  reached every gating surface: `zerodiff replay`, `zerodiff guard check`,
  and `zerodiff.testing.verify_traces()` (the one-line CI gate the README
  recommends). Reports now carry a distinct `no_data` verdict; the two
  CLI commands exit `2` with an explanatory message, and `verify_traces()`
  raises the new `NoBehaviorsReplayed`. `zerodiff record` already guarded
  the equivalent case on the recording side — replay simply never did.
- **Attestations could sign, and later "verify" as clean, a failed
  verification.** `zerodiff attest` stored the report's verdict but never
  checked it, and `verify-attestation` validated only the signature and
  digests — so an attestation of a diverged run verified green and exited
  0. `attest` now refuses a non-matched verdict unless you explicitly pass
  `--allow-diverged` (for deliberately attesting a failure), and
  `verify-attestation` reports a non-matched verdict as a problem.
- **`zerodiff migrate --attest` didn't pin the rewrite it just verified.**
  It never passed the rewrite files to the attestation, so — unlike
  `zerodiff attest --code` — a backdoor appended to the verified rewrite
  afterwards was invisible to `verify-attestation`. Since the README's
  flagship `migrate` example ends in `--attest` with no `--code`, the
  most-copied path produced the weakest evidence. `migrate` now pins the
  mapped rewrite files by default (reusing `loop.rewrite_files`).

Fixed — gates and evidence that quietly covered less than they claimed:

- **The quality gate passed vacuously when it couldn't find the rewrite
  on disk.** Replay resolves the rewrite by *import*; the gate resolved it
  by *filesystem path*. A rewrite that imports fine but doesn't sit where
  the mapping implies (installed package, `src/` layout, namespace
  package) was scanned as an empty file list and reported a clean gate
  over code it never read. The loop now refuses to report a clean gate it
  couldn't actually run.
- **`verify-attestation` ignored trace files *added* after signing.** It
  checked that attested files were unchanged, but never that unattested
  ones hadn't appeared beside them — so new, uncovered behaviors read as
  part of the signed set. Extras are now reported.
- **`attest --code` ran the quality gate with default settings**, ignoring
  the project's `[quality]` config, so a signed bundle could report errors
  the team's own gate was configured to skip. It now uses the same config
  every other call site does.
- **The MCP server never restored its working directory.** A
  `zerodiff_replay` call with `workdir` relocated the long-lived server
  permanently, so later calls — including ones passing no `workdir` —
  silently resolved against the previous call's project.
- **`migrate --driver` destroyed Windows paths.** POSIX splitting treats
  backslash as an escape, so `--driver "python scripts\run.py"` ran the
  wrong command. Split is now platform-correct (and still strips the
  quotes around a quoted executable, which non-POSIX splitting leaves on).
- `zerodiff-fix-prompt.md` — which embeds recorded inputs/outputs *and* the
  original module source — was left in the working directory after every
  agent run. It's now removed once the agent finishes, and `zerodiff init`
  adds it (and `*.key`) to `.gitignore`.
- `zerodiff llm-check` exited `1` (the "divergences found" code) on an
  unreachable endpoint or bad key. It now exits `2`, so CI can tell "we
  never ran" apart from "the rewrite is wrong."

Fixed — silent config failure:

- `[[scrub.regex]]` (standard TOML array-of-tables) silently misparsed
  into a garbage key on Python 3.8–3.10, so configured regex scrubbers
  never ran and no error was raised — despite the reader's own promise to
  reject unsupported syntax. It now raises, pointing at the flat
  `regex = ["pattern", ...]` form that does work on the fallback parser.

Polish:

- `replay --jobs 0` (or negative) silently ran serial, *non-isolated*
  replay despite `--jobs` advertising isolated workers; it's now rejected.
- A report that parses as JSON but isn't a ZeroDiff report produced a raw
  `KeyError` traceback instead of a readable error.
- `load_unique_traces` deduplicated id-less traces against each other
  (`None == None`), silently collapsing hand-edited or malformed traces
  into one behavior.
- `zerodiff demo` created a new temp directory on every run and never
  removed it. It now reuses one stable location — the demo intentionally
  leaves its files for inspection, so deleting them would defeat the point.
- `zerodiff record`'s summary reported the trace *directory's* total
  boundary count as though this run had touched them all; when appending
  to existing traces it now says so.
- MCP server docstring said "two tools" (it exposes three — `zerodiff_quality`
  since 0.8.0); dead imports removed; a dead conditional in the JUnit
  failure count simplified.

251 tests (up from 221). All 11 validation cohorts still replay clean and
the seeded-bug rewrite in `examples/legacy_pricing` is still caught.

## 0.13.0 — 2026-07-26 (comparison-core audit: three false matches fixed)

An audit of the comparison core found cases where ZeroDiff reported
**matched** for values that behave differently. For a verification harness
those are the worst possible defect, so they lead this release. Every fix
below is pinned by a regression test in `tests/test_v013.py` (221 tests,
up from 173); all 11 validation cohorts still replay clean, and the
seeded-bug rewrite in `examples/legacy_pricing` is still caught.

Fixed — silent false matches:

- **`frozenset` vs `set` and `bytes` vs `bytearray` compared as equal.**
  Both pairs share an encoding marker and are told apart by a sibling flag
  (`frozen`, `mutable`) that the differ recursed straight past. A rewrite
  returning a mutable buffer where the original returned an immutable one
  now diverges as a `type_mismatch`.
- **A dict could impersonate the type it names.** `{"__tuple__": [1, 2]}`
  encoded byte-identically to the tuple `(1, 2)`, so the two compared as
  equal *and* `decode()` handed the rewrite a tuple where the original got
  a dict. String-keyed dicts holding a reserved marker key now encode
  through the explicit pair form. Existing traces are unaffected (that form
  already existed); re-recording such a dict changes its trace id.

Fixed — accuracy of evidence:

- `float_tolerance` was silently ignored inside dataclasses and enum
  values; they now compare field-by-field, which also means a one-field
  mismatch reports `output.<field>` instead of dumping both objects at
  `output` — the hint the agent loop actually needs.
- Scrubbers could not normalize noise inside unserializable values: the
  `repr` was scrubbed but its fingerprint was not recomputed, so two
  now-identical reprs were still reported as differing. Digests are
  re-derived after scrubbing.
- `record_class` wrapped already-wrapped static and class methods on a
  second call, recording two traces per call and inflating the behavior
  count.
- A harness error mid-trace counted the trace as replayed twice, so
  reports and signed attestations could claim more replays than there were
  traces.
- `replay --in-order` sorted by wall-clock timestamp before the monotonic
  `seq` counter; a clock step during recording could misorder the very
  replay whose purpose is chronology.
- Divergence reports capped at 25 per trace stopped silently. A capped
  trace now carries an explicit `divergences_truncated` entry.

Fixed — gate and agent robustness:

- The quality gate only recognized fully dotted calls, so
  `from subprocess import run; run(..., shell=True)`,
  `from os import system`, and `import os as o` all passed unblocked.
  Import bindings are now resolved before the rules run.
- The built-in agent crashed the whole loop on a response that did not
  match the documented shape (empty `choices`, missing `message`, or a
  non-JSON body from a proxy). These now fail the iteration cleanly —
  the case that matters for `openai-compatible` third-party endpoints.

Added:

- `zerodiff.unwrap()` and `zerodiff.unwrap_class()` undo `wrap()` /
  `record_class()`; instrumentation previously lasted for the life of the
  process and leaked between tests sharing an interpreter.
- Boundary resolution is cached per replay run (10k-behavior replays no
  longer re-resolve per trace), and the recorder's dropped-trace counter is
  lock-guarded so threaded recording cannot lose counts.

## 0.12.0 — 2026-07-06 (rename: Retrace -> NoDrift)

- the product was renamed **Retrace -> NoDrift** (package `nodrift`, CLI
  `nodrift`, config `nodrift.toml`, env vars `NODRIFT_*`) after an
  availability sweep found the old name collided with a funded dental-AI
  company at retrace.ai and an adjacent agent-replay product at
  retraceai.tech
- no behavior changes; full suite green before and after
- (NoDrift was itself superseded by **ZeroDiff** in 0.15.0 — see above)

## 0.11.0 — 2026-07-05 (guard, coverage confidence, class ergonomics)

- `zerodiff guard baseline` / `zerodiff guard check`: the dependency-
  upgrade safety net -- record before upgrading, replay after; identity
  mapping on purpose (the upgraded package lives behind the same names)
- coverage confidence in every report: boundaries, distinct behaviors,
  exception-path share; insights flags boundaries recorded with zero
  error paths
- class ergonomics: dataclass and Enum values now RECONSTRUCT at replay
  when their class is importable (methods taking/returning dataclasses
  become fully replayable); `zerodiff.record_class()` instruments a
  class's public/static/class methods; `wrap()` accepts "Class.method"
- `zerodiff insights --json`; examples/ index README

## 0.10.2 — 2026-07-05 (cold-clone audit)

- packaging version is now single-sourced from `zerodiff.__version__`
  (pip metadata had been stuck at 0.1.0 since the first release)
- README documents `zerodiff insights`; changelog backfilled for 0.10.1
- audit verified from a fresh GitHub clone: 168 tests, demo, pricing
  example (good + buggy + insights), stdnum committed rewrites 269/269,
  attest/verify/history, MCP tools/list — all green with zero setup
  beyond `pip install -e .`

## 0.10.1 — 2026-07-05 (hard live cohort)

- loop stall detection catches A-B-A-B oscillation (fingerprint memory),
  found live when validators cycled 14<->23 under gpt-4o
- `replay_all` guards in_order+jobs at the API level
- hard cohort documented in VALIDATION.md: chevron 23/77 (then
  regression to 0), validators oscillation, dotenv 12/19 -- 148
  would-have-shipped divergences held at the gate

## 0.10.0 — 2026-07-05 (self-improvement loops + live cohort)

- `zerodiff insights`: mines your report and history locally into
  concrete next actions (adapters for weak comparisons, float_tolerance
  for numeric noise, hot boundaries, attest/CI habits after a green
  streak, regression pointer to the last green commit)
- inline quality suppressions with an audit trail:
  `# zerodiff-quality: ignore[rule]` on the flagged line
- CI now dogfoods the quality gate on ZeroDiff's own source
- resolver diagnostics: a rewrite module that exists but fails to import
  (relative imports, missing deps) now surfaces the actual import error
  in the missing_boundary hint; agent prompt + scaffold demand
  standalone modules (found via live semver run, where the model
  "fixed" a relative import by inventing a nonexistent module)
- live cohort documented in VALIDATION.md: gpt-4o-mini one-shots
  pytimeparse (42/42) and roman (10,083/10,083) fully unattended;
  semver reaches 275/277 with gpt-4o — stuck on the same two
  bump_prerelease quirks that fooled the human first pass
- docs/PRICING.md: Free / Team / Enterprise / Verified Migration tiers

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
  config in zerodiff.toml
- the built-in agent is least-privilege by design: no shell, no tools,
  output protocol is full-file sentinel blocks, writes restricted to the
  allowlisted rewrite files (path traversal rejected), and everything it
  writes still passes the quality gate and replay
- `zerodiff llm-check`: validate key/model/endpoint with one tiny
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
  `zerodiff replay --in-order` replays every call (no dedup) in recorded
  order
- **agent-loop economics**: stall detection (identical problems two
  iterations running → stop early), `--agent-timeout` (default 1800s),
  and prompts now name the rewrite files and the attempt number
- **parallel replay**: `--jobs N` shards across isolated workers
  (verified identical counts to serial on 10k behaviors)
- **coherence**: MCP server gained `zerodiff_quality`; attestations with
  `--code` now embed the quality-gate outcome in the signed body and
  accept `ZERODIFF_ATTEST_KEY`; reports flag Python-version drift between
  record and replay
- robustness: markdown reports cap at 100 divergences; unreadable files
  become gate findings; `zerodiff init` template includes `[quality]`

## 0.7.0 — 2026-07-04

- security/quality gate (docs/SAFE_CODING.md): zero-dependency AST
  analysis blocking eval/exec, shell=True, SQL interpolation, hardcoded
  secrets, unsafe deserialization, disabled TLS verification, insecure
  tempfiles; warns on weak hashes, exception-swallowing, mutable
  defaults, and length/complexity/nesting budget violations
- enforced in `zerodiff loop` / `zerodiff migrate` by default (findings are
  appended to the agent's fix prompt; the loop won't go green while
  blocking findings remain; `--no-quality` opts out); standalone
  `zerodiff quality FILE...`; budgets configurable via `[quality]` in
  zerodiff.toml
- secure-coding rules embedded in every agent fix prompt

## 0.6.0 — 2026-07-04

- `zerodiff replay` warns loudly when no `[map]` entry applied to any
  boundary (you were replaying the original against itself)
- attestations can pin rewrite source files (`zerodiff attest --code FILE`)
  and record the git commit; `verify-attestation` checks code digests too
- `zerodiff history` entries record the git commit
- new complex validation: python-stdnum (luhn/isbn/iban) through the full
  `zerodiff migrate` pipeline end to end
- repo governance: CHANGELOG, SECURITY.md, CONTRIBUTING.md, CI workflow

## 0.5.0 — 2026-07-04

- `zerodiff migrate`: the whole verified migration in one command — record
  → scaffold rewrite stubs from recorded boundaries → drive any agent CLI
  through the replay-fix loop → optional signed attestation

## 0.4.0 — 2026-07-04

- free tier: `zerodiff init`, `zerodiff demo`, `zerodiff.testing.verify_traces()`
  pytest one-liner, `zerodiff replay --junit-out`
- Enterprise (COMMERCIAL.md): `zerodiff attest` / `verify-attestation`
  (HMAC-signed tamper-evident evidence), `zerodiff history`

## 0.3.0 — 2026-07-03

- `zerodiff loop`: unattended replay→agent→replay loop for any agent CLI
- `zerodiff mcp`: zero-dependency MCP server (Claude Code, Codex, Copilot,
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
