# Security policy

## Reporting a vulnerability

Email <husamalkinani92@gmail.com> with "SECURITY" in the subject. You will
get an acknowledgement within 72 hours. Please do not open public issues
for suspected vulnerabilities.

## Security model, stated plainly

- **Retrace makes no network calls.** Recording, replay, reporting, and
  attestation are entirely local. Nothing is uploaded anywhere.
- **Traces contain real runtime data.** Treat the traces directory like a
  database dump: gitignored by default (`retrace init`), redactable at
  record time via `redact_fields` (redacted values never reach disk).
- **Replay executes the code under test.** In-process replay runs the
  rewrite inside the harness process; use `--isolate` for untrusted
  rewrites (worker subprocess; crashes/hangs are contained and reported).
  Replaying side-effecting code performs the side effects — point replay
  at disposable environments.
- **`retrace loop` / `retrace migrate` run the agent command you supply**
  with your shell and your permissions. Retrace does not sandbox your
  agent; choose its permission flags deliberately.
- **Attestations use HMAC-SHA256** with a shared key: they prove integrity
  to anyone holding the key (tamper-evidence), not third-party
  non-repudiation. Keep the key out of the repo; rotate it like any
  credential.
