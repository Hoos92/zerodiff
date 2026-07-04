# Retrace architecture

Retrace is a behavioral equivalence harness. It records what code *actually
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
| `recorder.py`   | `@retrace.record` decorator, `retrace.wrap()`, activation via API or `RETRACE_TRACE_DIR` env var; captures args/kwargs/return/exception per call |
| `serializer.py` | canonical, deterministic encoding of Python values to JSON-safe trees; adapter registry; opaque fallback with digest |
| `store.py`      | JSONL trace files (one per boundary), schema versioning, iteration |
| `config.py`     | `retrace.toml` loading (mappings, scrubbers); minimal built-in TOML-subset reader so Python 3.8 works with zero dependencies |
| `scrubbers.py`  | noise normalization applied to both sides before diffing: ignored fields, regex scrubs (UUID/timestamp built-ins), redaction |
| `replayer.py`   | resolves each recorded boundary through the old→new mapping, decodes inputs, invokes the replacement with per-call isolation |
| `differ.py`     | deep structural diff producing typed `Divergence` objects with paths and agent-actionable hints; float tolerance lives here |
| `report.py`     | `retrace-report.json` (machine/agent-first) and `retrace-report.md` (human) |
| `cli.py`        | `retrace record | replay | report`; exit codes 0/1/2 |

## Trace schema (JSONL, one call per line)

```json
{"schema": 1,
 "id": "<sha256 of boundary + canonical input>",
 "boundary": {"kind": "function", "target": "billing.pricing.calc_price"},
 "input": {"args": ["<encoded>"], "kwargs": {}},
 "output": {"type": "return", "value": "<encoded>"},
 "meta": {"ts": "2026-07-03T10:00:00Z", "duration_ms": 1.2,
          "py": "3.8.5", "retrace": "0.1.0"}}
```

- `output.type` is `"return"` or `"exception"`; exceptions record
  `{"type": "ValueError", "message": "..."}`. **Exceptions are first-class
  behavior**: the rewrite must raise the same exception type for the same
  input — silently returning a value where the original raised is a
  divergence (a common and dangerous AI-rewrite failure mode).
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
  comparison is flagged `weak_comparison` in the report — Retrace never
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
| `weak_comparison`     | opaque digests differ — a change Retrace can see but not explain |
| `replay_error`        | the harness itself failed on this trace (reported, never hidden) |

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
- **In-process replay**: the rewrite is imported into the harness process.
  A hostile or crashing rewrite can take the run down (subprocess isolation
  is a later phase); per-call exceptions are contained.
- **Recording overhead** makes it suited to test/staging/driver runs, not hot
  production paths.
- **Concurrency**: the JSONL appender is safe for single-process recording;
  multi-process recording to the same directory is not yet coordinated.
