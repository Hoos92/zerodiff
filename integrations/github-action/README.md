# Retrace GitHub Action

Gates pull requests on recorded behavior: if any recorded behavior of the
original code diverges in the PR's code, the check fails and the full
divergence report lands in the job summary.

```yaml
# .github/workflows/retrace.yml
name: behavioral-gate
on: [pull_request]
jobs:
  retrace:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: Hoos92/retrace/integrations/github-action@main
        with:
          traces-dir: traces
          map: "billing:billing_v2"
```

Commit your recorded traces for the boundaries you want protected (traces
of *code under migration* are fixtures — record them from a driver, review
them for sensitive data or use `redact_fields`, then commit them like any
other test fixture). Exit code 1 on divergence fails the check; the
markdown report is appended to the workflow's step summary.
