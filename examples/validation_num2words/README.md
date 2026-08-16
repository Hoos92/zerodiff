# Validation: `num2words` (github.com/savoirfairelinux/num2words)

High complexity — linguistic rule tables (English cardinal, ordinal,
ordinal_num, year). Best finds: an undocumented year grammar (centuries
divisible by ten read as cardinals — "two thousand and one" — while others
pair up — "nineteen oh-one", "ten sixty-six", "twenty ten"), and a type
error that formats the *value* into its message
(`type(None) not in [long, int, float]`).

```bash
pip install num2words
zerodiff record -o traces -- python run_scenarios.py
zerodiff replay -t traces
```

See [docs/VALIDATION.md](../../docs/VALIDATION.md) for first-pass numbers.
