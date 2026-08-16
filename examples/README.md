# Examples index

**Before you start:** every example records the *real* upstream library,
so each one needs network access and `pip install <that library>` first
(the command is in each README). No traces are committed — the point is
that you regenerate them and see the same divergences we did.

Commands are written for bash. In PowerShell, join the `\`-continued
lines into one, and write a signing key with
`Set-Content team.key 'your-team-signing-key!!'` instead of `printf`.

| directory | what it demonstrates |
|---|---|
| `legacy_pricing/` | the core loop on a toy module: equivalent rewrite 48/48, buggy rewrite caught (5 seeded bug classes) |
| `migration_dateutil/` | first real-library case study: dateutil.easter, 1,145 behaviors (docs/CASE_STUDY.md) |
| `validation_roman/`, `validation_inflection/`, `validation_humanize/` | cohort 2: clean-room rewrites vs recorded reality |
| `validation_word2number/`, `validation_slugify/`, `validation_num2words/` | cohort 3: complexity ladder (incl. a real arithmetic bug preserved on purpose) |
| `validation_stdnum/` | full `zerodiff migrate` pipeline with signed attestation (269 behaviors, 14 boundaries) |
| `validation_semver/`, `validation_humanfriendly/`, `validation_pytimeparse/` | cohort 4: spec-heavy parsers, live-LLM targets |

Full results and the live/hard LLM cohorts: [docs/VALIDATION.md](../docs/VALIDATION.md).
