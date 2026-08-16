"""JSONL trace storage: one file per boundary, one recorded call per line."""

import hashlib
import json
import os
import re
from typing import Any, Dict, Iterator, List

SCHEMA_VERSION = 1

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]")


def trace_id(boundary_target: str, encoded_input: Any) -> str:
    from .serializer import canonical_json

    payload = boundary_target + "\n" + canonical_json(encoded_input)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _file_for(trace_dir: str, boundary_target: str) -> str:
    safe = _SAFE_NAME_RE.sub("_", boundary_target)
    return os.path.join(trace_dir, safe + ".jsonl")


def append_trace(trace_dir: str, trace: Dict[str, Any]) -> None:
    os.makedirs(trace_dir, exist_ok=True)
    path = _file_for(trace_dir, trace["boundary"]["target"])
    line = json.dumps(trace, sort_keys=True, ensure_ascii=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")


def iter_traces(trace_dir: str) -> Iterator[Dict[str, Any]]:
    """Yield every stored trace. Raises ValueError on unknown schema versions
    so silent misreads can't masquerade as verification."""
    if not os.path.isdir(trace_dir):
        raise FileNotFoundError("trace directory not found: %s" % trace_dir)
    for name in sorted(os.listdir(trace_dir)):
        if not name.endswith(".jsonl"):
            continue
        path = os.path.join(trace_dir, name)
        with open(path, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                trace = json.loads(line)
                if trace.get("schema") != SCHEMA_VERSION:
                    raise ValueError(
                        "unsupported trace schema %r at %s:%d"
                        % (trace.get("schema"), path, lineno)
                    )
                yield trace


def load_unique_traces(trace_dir: str) -> List[Dict[str, Any]]:
    """All traces deduplicated by id (identical boundary+input recorded many
    times replays once)."""
    seen = set()
    unique = []
    for trace in iter_traces(trace_dir):
        tid = trace.get("id")
        if tid is None:
            # a malformed/hand-edited trace with no id must not dedup
            # against every other id-less trace and silently drop behaviors
            unique.append(trace)
            continue
        if tid in seen:
            continue
        seen.add(tid)
        unique.append(trace)
    return unique
