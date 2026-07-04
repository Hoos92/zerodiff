# Validation: `python-slugify` (github.com/un33p/python-slugify)

Medium complexity — a text pipeline with ~10 interacting options. Best
find: the original treats apostrophes *in the input* as separators
(`"C'est"` → `"c-est"`) but deletes apostrophes *introduced by
transliteration* (`"Компьютер"` → `"Komp'iuter"` → `"kompiuter"`) — two
separate quote passes, before and after transliteration, recovered
entirely from recorded behavior.

```bash
pip install python-slugify
retrace record --include slugify.slugify -o traces -- python run_scenarios.py
retrace replay -t traces
```

See [docs/VALIDATION.md](../../docs/VALIDATION.md) for first-pass numbers.
