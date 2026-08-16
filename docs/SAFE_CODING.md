# The security & quality gate

Behavioral fidelity is necessary but not sufficient: a rewrite can match
every recorded behavior and still be dangerous — `eval()` produces the
same answers as arithmetic, right up until the input is hostile. So
ZeroDiff enforces safe-code discipline in two places:

## 1. When the agent writes (prevention)

Every fix prompt the loop sends carries explicit secure-coding rules the
agent must follow: no eval/exec, no `shell=True`, parameterized SQL only,
no hardcoded secrets, never disable TLS verification, no swallowed
exceptions, no mutable defaults, size/complexity/nesting budgets, and no
new dependencies or I/O the original didn't have.

## 2. When ZeroDiff verifies (enforcement)

Rules are worthless without teeth. After every iteration, the gate
statically analyzes the rewrite files (stdlib `ast`, zero dependencies)
and **the loop will not go green while error-severity findings remain** —
they are appended to the fix prompt with hints, exactly like behavioral
divergences. `zerodiff migrate` and `zerodiff loop` have it on by default
(`--no-quality` to opt out); `zerodiff quality FILE...` runs it standalone.

### Blocking rules (error severity)

| rule | catches |
|---|---|
| `eval-exec` | `eval()` / `exec()` |
| `shell-injection` | `os.system`, `os.popen`, `subprocess` with `shell=True` |
| `unsafe-deserialization` | `pickle`/`marshal` loads, `yaml.load` without SafeLoader |
| `sql-injection` | SQL built with f-strings or %-formatting |
| `hardcoded-secret` | credential assignments and token-shaped literals (AWS, GitHub, Slack, API keys) |
| `tls-verification-disabled` | `verify=False`, `ssl._create_unverified_context` |
| `insecure-tempfile` | `tempfile.mktemp` |
| `syntax-error` | code that doesn't parse |

### Reported rules (warn severity — handed to the agent, don't block)

| rule | catches |
|---|---|
| `weak-hash` | md5/sha1 (fine for checksums, flagged for awareness) |
| `bare-except` / `silent-except` | `except:` and `except: pass` |
| `mutable-default` | mutable default arguments |
| `function-length` / `complexity` / `nesting` | budget violations (defaults: 60 lines, complexity 10, nesting 5) |

### Configuration

```toml
[quality]
max_function_lines = 40
max_complexity = 8
max_nesting = 4
disable = ["weak-hash"]
```

## Honest limits

Static analysis proves the absence of *these specific patterns*, not the
absence of all vulnerabilities — the same coverage-bounded honesty as the
behavioral side ("matched N of M recorded behaviors", never "correct").
For high-stakes code, the gate complements — never replaces — security
review. What it reliably does is stop the failure modes agents introduce
most often, automatically, on every iteration.
