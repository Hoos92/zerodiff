# Validation: `pytimeparse` (github.com/wroberts/pytimeparse)

Duration expressions (`"3d2h32m"`, `"1:02:03"`, `"1.2 minutes"`) with a
None-on-failure contract instead of exceptions. First pass: **40 of 42
matched**. The 2 misses are contract subtleties: a bare number (`"32"`)
is **not** a duration (None, not 32 seconds), and `"and"` is not a
connector (`"1 hour and 2 minutes"` → None) even though commas are fine.
Exactly the kind of permissive-grammar edge a rewrite "fixes" and breaks.

```bash
pip install pytimeparse
printf 'your-team-signing-key!!' > team.key   # PowerShell: Set-Content team.key 'your-team-signing-key!!'

nodrift migrate --driver "python run_scenarios.py" \
    --agent "python install_agent.py" --max-iters 3 \
    --attest --key-file team.key
```
