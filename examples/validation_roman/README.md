# Validation: `roman` (github.com/zopefoundation/roman)

Roman-numeral conversion with custom exception types — validates that
Retrace treats exception *types and messages* as first-class behavior.

```bash
pip install roman
retrace record --include roman -o traces -- python run_scenarios.py
retrace replay -t traces
```

`run_scenarios.py` sweeps `toRoman` over -5..5050 plus non-integer inputs,
round-trips every canonical numeral 1..4999 through `fromRoman`, and feeds
it two dozen malformed numerals. `roman_modern.py` is a clean-room rewrite;
see [docs/VALIDATION.md](../../docs/VALIDATION.md) for what the first pass
diverged on.
