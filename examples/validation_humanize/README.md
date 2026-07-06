# Validation: `humanize` (github.com/python-humanize/humanize)

Number and file-size formatting — fiddly thresholds, format strings, and
suffix tables (`1.0 kB` vs `1.0 KiB` vs `1000B`).

```bash
pip install humanize
nodrift record --include humanize.filesize --include humanize.number \
    -o traces -- python run_scenarios.py
nodrift replay -t traces
```

The mapping in `nodrift.toml` flattens two source modules
(`humanize.filesize`, `humanize.number`) into one rewrite module — the
kind of restructuring real migrations do. See
[docs/VALIDATION.md](../../docs/VALIDATION.md) for first-pass numbers.
