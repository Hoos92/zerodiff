# NoDrift architecture

NoDrift is a behavioral equivalence harness. It records what code *actually
does* at chosen boundaries, then verifies that a replacement implementation
does the same thing for every recorded input. The recorded behavior — not the
docs, not the tests, not anyone's memory — is treated as ground truth.

```
           RECORD                      REPLAY                    REPORT
 legacy code + traffic ──> traces/*.jsonl ──> rewrite + mapping ──> divergences
        recorder.py            store.py           replayer.py        report.py
        serializer.py                             differ.py
                                                  scrubbers.py
```

## Modules

| Module          | Responsibility |
|-----------------|----------------|
| `recorder.py`   | `@nodrift.record` decorator, `nodrift.wrap()`, activation via API or `NODRIFT_TRACE_DIR` env var; captures args/kwargs/return/exception per call; applies record-time redaction |
| `autohook.py`   | zero-edit auto-instrumentation: meta-path finder that wraps public module-level functions of modules matching `--include` patterns; injected into child processes via a temporary `sitecustomize` |
| `worker.py`     | isolated replay worker (`--isolate`): JSON-lines protocol on a duplicated fd while user prints divert to stderr; crashes/hangs become reported behavior |
| `loop.py`       | agent feedback loop (`nodrift loop`): replay → fix prompt with all divergences → invoke any agent CLI → repeat; always isolates so agent edits are re-imported fresh |
| `mcp_server.py` | zero-dep MCP server (`nodrift mcp`): JSON-RPC 2.0 over stdio exposing nodrift_replay/nodrift_report to MCP-capable agents; isolates by default because the server is long-lived |
| `testing.py`    | `verify_traces()` one-liner for pytest/unittest: raises BehaviorMismatch (an AssertionError) with a divergence digest |
| `scaffold.py`   | `nodrift init` (project scaffolding) and `nodrift demo` (guided 30-second example) |
| `enterprise.py` | commercial tier (see COMMERCIAL.md): HMAC-signed tamper-evident attestations, replay history |
| `migrate.py`    | `nodrift migrate`: the paired pipeline — record → scaffold rewrite stubs from recorded boundaries → agent loop → optional attestation. The agent writes; NoDrift judges |
| `agent.py`      | built-in minimal agent (`--llm provider:model`): zero-dep API client for anthropic/openai/openai-compatible endpoints; least-privilege fix-writer (no shell/tools, allowlisted writes via sentinel file blocks); `nodrift llm-check` preflight |
| `serializer.py` | canonical, deterministic encoding of Python values to JSON-safe trees; adapter registry; opaque fallback with digest |
| `store.py`      | JSONL trace files (one per boundary), schema versioning, iteration |
| `config.py`     | `nodrift.toml` loading (mappings, scrubbers); minimal built-in TOML-subset reader so Python 3.8 works with zero dependencies |
| `scrubbers.py`  | noise normalization applied to both sides before diffing: ignored fields, regex scrubs (UUID/timestamp built-ins), redaction |
| `replayer.py`   | resolves each recorded boundary through the old→new mapping, decodes inputs, invokes the replacement with per-call isolation |
| `differ.py`     | deep structural diff producing typed `Divergence` objects with paths and agent-actionable hints; float tolerance lives here |
| `report.py`     | `nodrift-report.json` (machine/agent-first) and `nodrift-report.md` (human) |
| `cli.py`        | `nodrift record | replay | report`; exit codes 0/1/2 |

## Trace schema (JSONL, one call per line)

```json
{"schema": 1,
 "id": "<sha256 of boundary + canonical input>",
 "boundary": {"kind": "function", "target": "billing.pricing.calc_price"},
 "input": {"args": ["<encoded>"], "kwargs": {}},
 "output": {"type": "return", "value": "<encoded>"},
 "meta": {"ts": "2026-07-03T10:00:00Z", "duration_ms": 1.2,
          "py": "3.8.5", "nodrift": "0.1.0"}}
```

- `output.type` is `"return"` or `"exception"`; exceptions record
  `{"type": "ValueError", "message": "..."}`. **Exceptions are first-class
  behavior**: the rewrite must raise the same exception type for the same
  input — silently returning a value where the original raised is a
  divergence (a common and dangerous AI-rewrite failure mode).
- **In-place argument mutation is first-class behavior too** (0.8):
  inputs are encoded *before* the call; afterwards, any argument whose
  encoding changed is stored under `"mutations"` (`{"0": <after>, "kw:name":
  <after>}`). Replay re-checks: a rewrite that returns the right value but
  forgets to mutate (or mutates differently) diverges at
  `mutation.args[N]`. An empty `mutations` dict means "captured, nothing
  mutated"; an absent field means "not captured" (old traces / `[record]
  mutations = false`) and is not checked.
- `meta.seq` is a process-wide counter preserving global chronology;
  `nodrift replay --in-order` replays **every** call (no deduplication)
  sorted by `(ts, seq)` — required for code with module-level state,
  where identical inputs legitimately produce different outputs.
- `boundary.kind` is extensible. v1 only emits `"function"`; an HTTP recorder
  can later emit `"http"` traces and reuse the differ/report layers unchanged.
- `id` is a content hash of boundary + canonical input, so identical calls
  deduplicate at replay time.

## Serialization

`serializer.encode()` produces a canonical JSON-safe tree:

- Primitives pass through; non-finite floats become `{"__float__": "nan"}` etc.
- `tuple` → `{"__tuple__": [...]}` (type fidelity is preserved — a rewrite
  that returns a list where the original returned a tuple is a real change).
- `dict` with non-string keys → `{"__dict__": [[k, v], ...]}` sorted by
  encoded key; string-keyed dicts stay plain objects (compared key-by-key,
  order-insensitive).
- `set`/`frozenset` → `{"__set__": [...]}` sorted canonically.
- `bytes` → base64, `datetime`/`date`/`time` → ISO, `Decimal` → string,
  `Enum` → type + value, dataclasses → type + fields.
- Anything else → `{"__opaque__": {"type": "...", "repr": "...",
  "digest": "..."}}`. Opaque values are compared by digest and every such
  comparison is flagged `weak_comparison` in the report — NoDrift never
  silently pretends it fully compared something it couldn't.
- Cycle detection and a depth cap protect the recorder from pathological
  structures; both degrade to opaque encoding rather than crashing the host
  program. **The recorder must never break the code it observes.**

`serializer.decode()` inverts the encoding for replay. Traces whose *inputs*
contain opaque values cannot be faithfully replayed; they are reported as
`skipped_unreplayable` rather than silently dropped.

## Divergence taxonomy

| kind                  | meaning |
|-----------------------|---------|
| `value_mismatch`      | same shape, different value at `path` |
| `type_mismatch`       | different type/shape at `path` (list vs tuple, int vs str…) |
| `exception_mismatch`  | raised vs returned, different exception type, or different message |
| `missing_boundary`    | mapping doesn't resolve to a callable in the rewrite |
| `weak_comparison`     | opaque digests differ — a change NoDrift can see but not explain |
| `replay_error`        | the harness itself failed on this trace (reported, never hidden) |
| `process_crash`       | (`--isolate` only) the rewrite killed or hung the worker process where the original completed |

Every divergence carries `boundary`, `trace_id`, `path`, `expected`, `actual`,
and a generated `hint` — a sentence written for a coding agent, e.g.:

> expected ValueError("quantity must be positive"), got return value 0 — the
> rewrite silently accepts input the original rejected; restore the guard in
> billing_v2.pricing.calc_price.

## Honest-guarantee rules (product invariants)

1. Reports state **"matched N of M recorded behaviors"** and list per-boundary
   coverage counts. The words "identical" or "equivalent" (unqualified) must
   not appear in generated reports.
2. Weak comparisons and skipped traces are always counted and shown in the
   summary, never folded into "matched".
3. Replay exit code is `1` if *any* divergence exists, `2` on harness error;
   `0` only when every replayed behavior matched and nothing was skipped
   (skips with zero divergences exit `0` but are prominently reported —
   they reduce coverage, not correctness).

## Known limitations (v1)

- **Coverage-bounded**: equivalence is proven only for recorded inputs.
- **Python-only, function-level**: methods are supported via module-level
  access (`module.Class.method`); closures and lambdas are not recordable.
- **Side effects pass through**: replaying a function that writes to a DB
  writes to the DB. VCR-style interception is a later phase; the README warns.
- **In-process replay by default**: the rewrite is imported into the
  harness process; per-call exceptions are contained. Use `--isolate` for
  untrusted rewrites — each call runs in a worker subprocess and crashes,
  `os._exit`, and hangs (per-call `--timeout`) are reported as
  `process_crash` divergences.
- **Auto-instrumentation scope**: `--include` wraps public module-level
  functions of filesystem-based modules only; class methods and closures
  need `nodrift.wrap` or the decorator. The injected `sitecustomize`
  shadows any existing one for that run.
- **Recording overhead** makes it suited to test/staging/driver runs, not hot
  production paths.
- **Concurrency**: the JSONL appender is safe for single-process recording;
  multi-process recording to the same directory is not yet coordinated.
  Replay can parallelize across isolated workers (`--jobs N`; incompatible
  with `--in-order`, since shards can't preserve global chronology).
- **Loop economics**: the agent loop stops early when two consecutive
  iterations produce an identical problem fingerprint (agent stalled) and
  kills agents that exceed `--agent-timeout` — no burning API spend on a
  stuck loop.
