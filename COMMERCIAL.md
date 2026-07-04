# Retrace licensing

Retrace is **open core**.

## Free (MIT) — everything a developer needs

The core harness is MIT-licensed, forever: record, replay (including
isolation), report (json/md/JUnit), scrubbing and redaction, auto-
instrumentation, the agent loop, the MCP server, the GitHub Action and
Claude Code hook, `retrace init`, `retrace demo`, and the
`retrace.testing` pytest helper. Use it anywhere, for anything.

## Retrace Enterprise — evidence and assurance for organizations

The `retrace/enterprise.py` module is source-available for evaluation and
non-production use; **production use requires a commercial license**:

| feature | what it's for |
|---|---|
| `retrace attest` / `verify-attestation` | signed, tamper-evident evidence bundles: prove to auditors, customers, or your own change board that the verification ran, what it covered, and that nobody altered the traces or report afterwards |
| `retrace history` / `replay --history` | verification results over time — the audit trail of a codebase's behavioral guarantees across migrations, upgrades, and agent activity |
| priority support & roadmap input | direct line for migration engagements |

Planned for the commercial tier: hosted report history and dashboards,
organization-wide policy ("no merge without attestation"), SSO, and
long-term evidence retention.

## Get a license

Email <husamalkinani92@gmail.com> with "Retrace Enterprise" in the
subject. Early-adopter terms are deliberately simple and inexpensive —
what matters most right now is working with real migrations.
