# Validation: `python-stdnum` (github.com/arthurdejong/python-stdnum) — the full pipeline

The hardest validation so far, and the only one run **end-to-end through
`zerodiff migrate`**: three modules at once (luhn, isbn, iban), a custom
exception hierarchy, and country-specific IBAN plug-ins.

```bash
pip install python-stdnum
printf 'your-team-signing-key!!' > team.key   # PowerShell: Set-Content team.key 'your-team-signing-key!!'

zerodiff migrate \
    --driver "python run_scenarios.py" \
    --agent "python install_agent.py" \
    --max-iters 3 --attest --key-file team.key
```

(`install_agent.py` is a scripted stand-in that installs the rewrites from
`impl_store/`; a real run points `--agent` at Claude Code, Codex, etc.)

The pipeline records 269 unique behaviors across 14 boundaries, scaffolds
`luhn_v2.py` / `isbn_v2.py` / `iban_v2.py` stubs, drives the agent until
**269 of 269 recorded behaviors match**, and signs an attestation. Then:

```bash
zerodiff attest -t traces --key-file team.key --code luhn_v2.py --code isbn_v2.py --code iban_v2.py
zerodiff verify-attestation --key-file team.key -t traces   # exit 0
# change one character of any attested file and verify again -> exit 1
```

Best finds (see docs/VALIDATION.md):

- Recording captured stdnum's **real internal signature** — its own
  `is_valid` calls `validate(number, check_country=...)`, a kwarg the
  driver never used, surfaced purely through nested-call recording.
- The **textbook example IBAN `BE68539007547034` is genuinely rejected**
  by stdnum's Belgian country plug-in (bank registry lookup) —
  `is_valid()` returns False on the string half the internet uses as the
  canonical "valid IBAN".
- **The mod-97 checksum is verified before length or country**, so a
  truncated GB IBAN raises `InvalidChecksum`, not `InvalidLength` — an
  exception-ordering contract invisible in any documentation.
- `to_isbn13("0-19-852663-6")` → `"978-0-19-852663-6"`: the converters do
  string surgery that **preserves the input's hyphenation**, not numeric
  conversion.
