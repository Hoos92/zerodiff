# Security policy

## Reporting a vulnerability

Email <husamalkinani92@gmail.com> with "SECURITY" in the subject. You will
get an acknowledgement within 72 hours. Please do not open public issues
for suspected vulnerabilities.

## Security model, stated plainly

- **The core harness makes no network calls.** Recording, replay,
  reporting, and attestation are entirely local; nothing is uploaded
  anywhere. The one exception is the optional built-in agent
  (`--llm` / `zerodiff llm-check`), which calls the LLM endpoint you
  configure with your key — see the `--llm` note below for exactly what
  it sends.
- **Traces contain real runtime data.** Treat the traces directory like a
  database dump: gitignored by default (`zerodiff init`), redactable at
  record time via `redact_fields` (redacted values never reach disk).
- **Replay executes the code under test.** In-process replay runs the
  rewrite inside the harness process; use `--isolate` for untrusted
  rewrites (worker subprocess; crashes/hangs are contained and reported).
  Replaying side-effecting code performs the side effects — point replay
  at disposable environments.
- **`zerodiff loop` / `zerodiff migrate` run the agent command you supply**
  with your shell and your permissions. ZeroDiff does not sandbox your
  agent; choose its permission flags deliberately.
- **The built-in agent (`--llm`) sends fix prompts to your chosen LLM
  provider.** Fix prompts contain divergence details (recorded
  inputs/outputs) and the ORIGINAL modules' source code as reference —
  apply `redact_fields` at record time if traces may contain secrets,
  and treat the legacy source as part of what you're sharing with the
  provider. (BYO agents have the same data path via
  their own vendor.) The built-in agent itself is least-privilege: no
  shell, no tools, writes only to the allowlisted rewrite files, and its
  output still passes the quality gate and replay.
- **Attestations use HMAC-SHA256** with a shared key: they prove integrity
  to anyone holding the key (tamper-evidence), not third-party
  non-repudiation. Keep the key out of the repo; rotate it like any
  credential.
