# Examples index

| directory | what it demonstrates |
|---|---|
| `legacy_pricing/` | the core loop on a toy module: equivalent rewrite 48/48, buggy rewrite caught (5 seeded bug classes) |
| `migration_dateutil/` | first real-library case study: dateutil.easter, 1,145 behaviors (docs/CASE_STUDY.md) |
| `validation_roman/`, `validation_inflection/`, `validation_humanize/` | cohort 2: clean-room rewrites vs recorded reality |
| `validation_word2number/`, `validation_slugify/`, `validation_num2words/` | cohort 3: complexity ladder (incl. a real arithmetic bug preserved on purpose) |
| `validation_stdnum/` | full `nodrift migrate` pipeline with signed attestation (269 behaviors, 14 boundaries) |
| `validation_semver/`, `validation_humanfriendly/`, `validation_pytimeparse/` | cohort 4: spec-heavy parsers, live-LLM targets |

Full results and the live/hard LLM cohorts: [docs/VALIDATION.md](../docs/VALIDATION.md).
