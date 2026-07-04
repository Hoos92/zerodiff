# Retrace

**Prove your rewrite behaves like the original — before you trust it.**

AI agents can rewrite and migrate legacy code cheaply. The blocker is trust:
the original has years of undocumented behavior baked in, and nobody wants to
deploy a rewrite on an agent's word. Retrace closes that gap with recorded
evidence:

1. **Record** — run the legacy code under real or driver traffic and capture
   every call at chosen function boundaries: inputs, outputs, and exceptions.
2. **Replay** — run the same recorded inputs against the rewritten code
   (written by any agent, or any human — Retrace doesn't care).
3. **Report** — get every behavioral divergence as a machine-readable report
   with actionable hints an agent can fix in a loop, plus a human-readable
   summary. Exit codes make it a CI gate with zero glue.

```
$ retrace record -o traces -- python driver.py
  recorded 1,204 calls across 3 boundaries -> traces/

$ retrace replay -t traces --map "billing:billing_v2"
  replayed 1,204 recorded behaviors
  matched  1,198   diverged 6   -> retrace-report.json, retrace-report.md
  exit code 1
```

## Quick start

```bash
pip install -e .
```

Record with **zero source edits** — `--include` auto-instruments every
public function of matching modules as they load:

```bash
retrace record --include billing -o traces -- python run_legacy_scenarios.py
retrace replay -t traces --map "billing:billing_v2"
```

Or mark boundaries explicitly when you want tighter control:

```python
import retrace

@retrace.record                      # option A: decorate
def calc_price(order): ...

retrace.wrap("billing.pricing", "calc_price")   # option B: wrap from outside
```

Replaying an untrusted rewrite? `--isolate` runs every call in a worker
subprocess: a rewrite that crashes the interpreter, calls `os._exit`, or
hangs becomes a reported `process_crash` divergence instead of taking the
harness down:

```bash
retrace replay -t traces --isolate --timeout 10
```

Exit codes: `0` = every recorded behavior matched, `1` = divergences found,
`2` = harness error. `retrace-report.json` is designed to be fed straight back
to a coding agent; `retrace-report.md` is for humans.

## What Retrace does and does not claim

Retrace is deliberately honest about its guarantees:

- It proves equivalence **over the recorded behaviors only** — never over all
  possible behaviors. A passing report says "matched N of N recorded
  behaviors", not "the systems are identical". Coverage is only as good as
  the traffic you record.
- **Side effects are not intercepted in v1.** A recorded function that writes
  to a database or calls the network will really do so again during replay.
  Record and replay side-effecting code only against disposable environments.
- Objects Retrace can't fully serialize are compared by type + repr digest and
  flagged as *weak comparisons* in the report, so trust is never overstated.
- Traces contain real runtime data, which may be sensitive. The default
  `.gitignore` excludes trace directories; redaction scrubbers are available.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design and
limitation notes.

## Handling noise (timestamps, floats, UUIDs)

Real code is noisy. Configure per-boundary scrubbers in `retrace.toml` so
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
  modern rewrite, with zero source edits. Retrace caught the one divergence
  a human review would wave through. Write-up with numbers:
  [docs/CASE_STUDY.md](docs/CASE_STUDY.md).

## Status

v0.2 — Python 3.8+, function-level boundaries, zero runtime dependencies.
New in 0.2: zero-edit auto-instrumentation (`--include`), subprocess-isolated
replay with crash/hang detection (`--isolate`), record-time redaction.
Roadmap: agent feedback-loop driver, MCP server, HTTP service-level
recording, side-effect interception.

MIT licensed.
