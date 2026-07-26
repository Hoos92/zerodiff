"""Noise normalization applied to encoded trees before diffing.

Scrubbers run on *both* the recorded and the replayed tree, so legitimate
noise (timestamps, UUIDs, request ids) doesn't drown real divergences.
A scrubbed node is replaced by the sentinel string below — visible in
reports, so a reader can always tell that a field was excluded rather than
matched.
"""

import re
from typing import Any, Dict, List, Optional

SCRUBBED = "__scrubbed__"
REDACTED = "__redacted__"

BUILTIN_PATTERNS = {
    "uuid": re.compile(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
        r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    ),
    "timestamp": re.compile(
        r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
    ),
}


def _field_matches(key: str, path: str, patterns: List[str]) -> bool:
    for pat in patterns:
        if pat == key or pat == path:
            return True
        # "*.name" matches a key at any depth
        if pat.startswith("*.") and pat[2:] == key:
            return True
    return False


def scrub(tree: Any, ignore_fields: List[str], regexes: List[Any],
          path: str = "output", redact_fields: Optional[List[str]] = None
          ) -> Any:
    """Return a copy of the encoded tree with configured noise normalized.

    ``redact_fields`` works like ``ignore_fields`` but uses a distinct
    sentinel; the recorder also applies it at record time, so redacted
    values are never written to disk.
    """
    redact_fields = redact_fields or []
    if isinstance(tree, str):
        out = tree
        for rx in regexes:
            out = rx.sub(SCRUBBED, out)
        return out
    if isinstance(tree, list):
        return [scrub(v, ignore_fields, regexes, "%s[%d]" % (path, i),
                      redact_fields)
                for i, v in enumerate(tree)]
    if isinstance(tree, dict):
        # marker nodes pass through with their contents scrubbed
        result = {}
        for key, value in tree.items():
            child_path = "%s.%s" % (path, key)
            if key.startswith("__"):
                result[key] = scrub(value, ignore_fields, regexes,
                                    child_path, redact_fields)
            elif _field_matches(key, child_path, redact_fields):
                result[key] = REDACTED
            elif _field_matches(key, child_path, ignore_fields):
                result[key] = SCRUBBED
            else:
                result[key] = scrub(value, ignore_fields, regexes,
                                    child_path, redact_fields)
        return _refingerprint(result)
    return tree


def _refingerprint(node: Dict[str, Any]) -> Dict[str, Any]:
    """An opaque value's digest was computed at record time from its raw
    repr. Once scrubbers have normalized that repr, the stale digest would
    report two now-identical reprs as differing -- so recompute it."""
    opaque = node.get("__opaque__")
    if not isinstance(opaque, dict) or "digest" not in opaque:
        return node
    from .serializer import opaque_digest

    rescrubbed = dict(opaque)
    rescrubbed["digest"] = opaque_digest(str(opaque.get("type", "")),
                                         str(opaque.get("repr", "")))
    out = dict(node)
    out["__opaque__"] = rescrubbed
    return out


def compile_scrubbers(cfg, boundary: str) -> Dict[str, Any]:
    """Resolve config into the concrete scrub plan for one boundary."""
    regexes = []
    for name in cfg.builtin_scrubbers(boundary):
        rx = BUILTIN_PATTERNS.get(name)
        if rx is None:
            raise ValueError(
                "unknown builtin scrubber %r (available: %s)"
                % (name, ", ".join(sorted(BUILTIN_PATTERNS)))
            )
        regexes.append(rx)
    for entry in cfg.regex_scrubs(boundary):
        pattern = entry.get("pattern") if isinstance(entry, dict) else entry
        regexes.append(re.compile(pattern))
    return {
        "ignore_fields": cfg.ignore_fields(boundary),
        "redact_fields": cfg.redact_fields(boundary),
        "regexes": regexes,
        "float_tolerance": cfg.float_tolerance(boundary),
    }
