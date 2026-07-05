# Validation: `semver` (github.com/python-semver/python-semver)

The semver.org precedence rules, all-pairs across 15 tricky versions (225
comparisons), plus parse/bump/finalize — run end-to-end through
`retrace migrate` with a signed attestation at the finish.

First pass: **275 of 277 matched**. Both misses were `bump_prerelease`:
the original bumps the *rightmost embedded number* (`alpha.7.x` →
`alpha.8.x`), and for a prerelease with no digits at all
(`1.2.3-alpha`) it is silently a **no-op** — behavior no docstring
mentions and no reviewer would guess.

```bash
pip install semver
retrace migrate --driver "python run_scenarios.py" \
    --agent "python install_agent.py" --max-iters 3 \
    --attest --key-file team.key
```
