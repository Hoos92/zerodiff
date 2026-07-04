# Validation: `word2number` (github.com/akshaynagpal/w2n)

Simple complexity — one parser function, a decade of quirks. The star
find of the validation program: the original really returns
**1,003,000,002** for `word_to_num("one billion two million")` (a genuine
arithmetic bug), silently ignores unknown words (`"one two hello"` → `3`),
and returns `0` for the bare word `"point"`. A faithful drop-in must
reproduce all of it.

```bash
pip install word2number
retrace record -o traces -- python run_scenarios.py
retrace replay -t traces
```

See [docs/VALIDATION.md](../../docs/VALIDATION.md) for first-pass numbers.
