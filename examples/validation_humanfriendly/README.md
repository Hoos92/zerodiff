# Validation: `humanfriendly` (github.com/xolox/python-humanfriendly)

Size/timespan parsing and formatting — the cohort's hardest quirk mine.
First pass: **105 of 113 matched**. The 8 misses:

- `format_timespan` silently **truncates to the three largest units** —
  `90061s` really formats as "1 day, 1 hour and 1 minute"; the second
  vanishes.
- a humanfriendly **year is 52 weeks** (31,449,600s), not 365.25 days —
  both when parsing "1y" and when formatting.
- the size tokenizer rejects scientific notation (`"1e3 KB"` raises) yet
  **ignores trailing junk** (`"1 KB extra"` → 1000), and its error
  message embeds the exact token list, `'1..5'` tokenizing as
  `[1, '..', 5]`.

```bash
pip install humanfriendly
printf 'your-team-signing-key!!' > team.key

nodrift migrate --driver "python run_scenarios.py" \
    --agent "python install_agent.py" --max-iters 3 \
    --attest --key-file team.key
```
