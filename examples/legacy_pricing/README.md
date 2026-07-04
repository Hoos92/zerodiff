# Demo: verifying a rewrite of a legacy pricing module

Three implementations of the same module:

- `pricing.py` — the "legacy" original, full of quirks (bulk discount starts
  *at* ten units, tier discount applies after the coupon, callers match on
  exact error messages…).
- `pricing_v2.py` — a clean modern rewrite that preserves behavior.
- `pricing_buggy.py` — a rewrite with **five seeded bugs** of the kinds AI
  rewrites really introduce: a silently-removed guard, an off-by-one, a type
  change, a rounding change, and a reworded error message.

Run the loop (from this directory):

```bash
# 1. record what the legacy code actually does (~90 calls, 3 boundaries)
retrace record -o traces -- python driver.py

# 2. replay against the good rewrite -> everything matches, exit code 0
retrace replay -t traces

# 3. replay against the buggy rewrite -> all five bugs caught, exit code 1
retrace replay -t traces --map pricing:pricing_buggy

# 4. read the human report, or feed retrace-report.json to a coding agent
retrace report --format md
```

Note what step 3 catches that a typical test suite doesn't: the buggy rewrite
*runs fine* — it just behaves differently. Retrace flags every divergence
with the exact input that exposes it and a hint aimed at the agent that will
fix it.
