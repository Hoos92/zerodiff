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

Mark the boundaries you care about in the legacy code (or wrap them from a
driver script without touching the source):

```python
import retrace

@retrace.record                      # option A: decorate
def calc_price(order): ...

retrace.wrap("billing.pricing", "calc_price")   # option B: wrap from outside
```

Record real behavior, then replay against the rewrite:

```bash
retrace record -o traces -- python run_legacy_scenarios.py
retrace replay -t traces --map "billing.pricing:billing_v2.pricing"
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

[scrub.boundaries."billing.pricing.make_receipt"]
ignore_fields = ["generated_at", "trace_id"]
```

## Demo

`examples/legacy_pricing/` contains a deliberately gnarly legacy pricing
module, an equivalent modern rewrite, and a rewrite with seeded behavioral
bugs. See [examples/legacy_pricing/README.md](examples/legacy_pricing/README.md)
to run the full record → replay → report loop in under a minute.

## Status

v0.1 — Python 3.8+, function-level boundaries, zero runtime dependencies.
Roadmap: import-hook auto-instrumentation, agent feedback-loop driver, MCP
server, HTTP service-level recording, side-effect interception.

MIT licensed.
