# Demo: verifying a rewrite of `dateutil.easter` (a real PyPI package)

Reproduces the case study in [docs/CASE_STUDY.md](../../docs/CASE_STUDY.md):
record the real behavior of `dateutil.easter.easter()` with **zero source
edits**, then verify a clean modern rewrite against it.

```bash
pip install python-dateutil

# 1. record ~1,100 real behaviors (no zerodiff code in any user file)
zerodiff record --include dateutil.easter -o traces -- python run_scenarios.py

# 2. replay against the modern rewrite
zerodiff replay -t traces
```

`easter_modern.py` already contains the post-fix version that matches
1,145/1,145 recorded behaviors. To see the gate catch the original
first-pass divergence, change the ValueError message in `easter()` to
anything else and replay — 4 exception_mismatch divergences, exit code 1,
with a hint telling you exactly how to fix it.
