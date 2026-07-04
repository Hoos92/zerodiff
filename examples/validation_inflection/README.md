# Validation: `inflection` (github.com/jpvanhal/inflection)

The Python port of Ruby on Rails' inflector — a decade of accumulated regex
rules for pluralization, camelization, and friends. The hardest of the
three validations: behavior lives in long, ordered rule tables full of
special cases nobody remembers.

```bash
pip install inflection
retrace record --include inflection -o traces -- python run_scenarios.py
retrace replay -t traces
```

Notable recorded quirk: `camelize("", uppercase_first_letter=False)` raises
`IndexError` in the original — a crash, but *its* crash. A faithful rewrite
must reproduce it, and Retrace enforces that. See
[docs/VALIDATION.md](../../docs/VALIDATION.md) for the first-pass numbers.
