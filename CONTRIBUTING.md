# Contributing

## Setup

```bash
pip install -e .[dev]
python -m pytest tests/ -q
```

(If your environment has stale global pytest plugins, run with
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`.)

## Ground rules

- **Python 3.8+ and zero runtime dependencies** in the `zerodiff/` package.
  The built-in TOML-subset reader exists for exactly this reason.
- **The recorder must never break the host program**: any failure inside
  recording is swallowed and counted, never raised.
- **Honest-guarantee invariants** (see docs/ARCHITECTURE.md): reports say
  "matched N of M recorded behaviors"; weak comparisons and skips are
  always surfaced, never folded into "matched". Changes that soften these
  claims will not be merged.
- Every behavior fix or feature lands with a test. The golden self-test
  (`tests/test_golden_example.py`) must stay green.
- `zerodiff/enterprise.py` is source-available under commercial terms (see
  COMMERCIAL.md); everything else is MIT.
