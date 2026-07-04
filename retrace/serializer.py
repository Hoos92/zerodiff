"""Canonical serialization of Python values to JSON-safe trees.

The encoding is deterministic: the same value always produces the same tree,
so trees can be hashed for trace ids and compared structurally by the differ.
Values that cannot be fully represented degrade to an ``__opaque__`` node
(type + repr + digest) instead of failing — the recorder must never break the
program it is observing.
"""

import base64
import dataclasses
import datetime
import decimal
import enum
import hashlib
import json
import math
import re
from typing import Any, Callable, List, Tuple

MAX_DEPTH = 30
MAX_REPR = 300

# 0x7f9a2c... memory addresses make reprs unstable across runs
_ADDR_RE = re.compile(r"0x[0-9a-fA-F]+")


class OpaqueValueError(Exception):
    """Raised by decode() when a tree contains a value that cannot be
    reconstructed (recorded opaquely). Such traces are unreplayable."""


_adapters: List[Tuple[type, Callable[[Any], Any]]] = []


def register_adapter(type_: type, encode_fn: Callable[[Any], Any]) -> None:
    """Register a custom encoder. ``encode_fn(value)`` must return a value
    that ``encode`` can handle (e.g. a dict of primitives)."""
    _adapters.append((type_, encode_fn))


def _stable_repr(value: Any) -> str:
    try:
        r = repr(value)
    except Exception:
        r = "<repr failed>"
    r = _ADDR_RE.sub("0xADDR", r)
    if len(r) > MAX_REPR:
        r = r[:MAX_REPR] + "..."
    return r


def _opaque(value: Any) -> dict:
    type_name = "{}.{}".format(type(value).__module__, type(value).__qualname__)
    stable = _stable_repr(value)
    digest = hashlib.sha256(
        "{}:{}".format(type_name, stable).encode("utf-8")
    ).hexdigest()[:16]
    return {"__opaque__": {"type": type_name, "repr": stable, "digest": digest}}


def encode(value: Any, _depth: int = 0, _seen: Any = None) -> Any:
    """Encode a Python value into a canonical JSON-safe tree."""
    if _seen is None:
        _seen = set()
    if _depth > MAX_DEPTH:
        return _opaque(value)

    if value is None or isinstance(value, (bool, int, str)):
        return value

    if isinstance(value, float):
        if math.isnan(value):
            return {"__float__": "nan"}
        if math.isinf(value):
            return {"__float__": "inf" if value > 0 else "-inf"}
        return value

    for type_, fn in _adapters:
        if isinstance(value, type_):
            try:
                return {
                    "__adapted__": {
                        "type": "{}.{}".format(
                            type(value).__module__, type(value).__qualname__
                        ),
                        "value": encode(fn(value), _depth + 1, _seen),
                    }
                }
            except Exception:
                return _opaque(value)

    if isinstance(value, (list, tuple, set, frozenset, dict)):
        vid = id(value)
        if vid in _seen:
            return {"__cycle__": True}
        _seen = _seen | {vid}

    if isinstance(value, list):
        return [encode(v, _depth + 1, _seen) for v in value]
    if isinstance(value, tuple):
        return {"__tuple__": [encode(v, _depth + 1, _seen) for v in value]}
    if isinstance(value, (set, frozenset)):
        items = [encode(v, _depth + 1, _seen) for v in value]
        items.sort(key=canonical_json)
        node = {"__set__": items}
        if isinstance(value, frozenset):
            node["frozen"] = True
        return node
    if isinstance(value, dict):
        if all(isinstance(k, str) for k in value):
            return {k: encode(v, _depth + 1, _seen) for k, v in value.items()}
        pairs = [
            [encode(k, _depth + 1, _seen), encode(v, _depth + 1, _seen)]
            for k, v in value.items()
        ]
        pairs.sort(key=lambda kv: canonical_json(kv[0]))
        return {"__dict__": pairs}

    if isinstance(value, bytes):
        return {"__bytes__": base64.b64encode(value).decode("ascii")}
    if isinstance(value, bytearray):
        return {"__bytes__": base64.b64encode(bytes(value)).decode("ascii"),
                "mutable": True}
    if isinstance(value, datetime.datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, datetime.date):
        return {"__date__": value.isoformat()}
    if isinstance(value, datetime.time):
        return {"__time__": value.isoformat()}
    if isinstance(value, decimal.Decimal):
        return {"__decimal__": str(value)}
    if isinstance(value, enum.Enum):
        return {
            "__enum__": {
                "type": "{}.{}".format(
                    type(value).__module__, type(value).__qualname__
                ),
                "name": value.name,
                "value": encode(value.value, _depth + 1, _seen),
            }
        }
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        try:
            fields = {
                f.name: encode(getattr(value, f.name), _depth + 1, _seen)
                for f in dataclasses.fields(value)
            }
            return {
                "__dataclass__": {
                    "type": "{}.{}".format(
                        type(value).__module__, type(value).__qualname__
                    ),
                    "fields": fields,
                }
            }
        except Exception:
            return _opaque(value)

    return _opaque(value)


def decode(tree: Any) -> Any:
    """Reconstruct a Python value from an encoded tree.

    Raises OpaqueValueError if the tree contains values that were recorded
    opaquely — those traces cannot be faithfully replayed.
    Enums, dataclasses and adapted values decode to plain structures (their
    encoded form) since the original classes may not exist at replay time;
    they are only needed for *comparison*, which happens on encoded trees.
    Inputs, however, must decode to real values — plain-structure decoding of
    an input would change what the replacement function receives, so inputs
    containing class-based values are treated as unreplayable too (v1).
    """
    if tree is None or isinstance(tree, (bool, int, float, str)):
        return tree
    if isinstance(tree, list):
        return [decode(v) for v in tree]
    if isinstance(tree, dict):
        if "__opaque__" in tree:
            raise OpaqueValueError(tree["__opaque__"].get("type", "unknown"))
        if "__cycle__" in tree:
            raise OpaqueValueError("cyclic structure")
        if "__adapted__" in tree or "__enum__" in tree or "__dataclass__" in tree:
            # cannot faithfully reconstruct the original class instance
            raise OpaqueValueError(
                (tree.get("__adapted__") or tree.get("__enum__")
                 or tree.get("__dataclass__")).get("type", "unknown")
            )
        if "__float__" in tree:
            return float(tree["__float__"])
        if "__tuple__" in tree:
            return tuple(decode(v) for v in tree["__tuple__"])
        if "__set__" in tree:
            items = {decode(v) for v in tree["__set__"]}
            return frozenset(items) if tree.get("frozen") else items
        if "__dict__" in tree:
            return {decode(k): decode(v) for k, v in tree["__dict__"]}
        if "__bytes__" in tree:
            raw = base64.b64decode(tree["__bytes__"])
            return bytearray(raw) if tree.get("mutable") else raw
        if "__datetime__" in tree:
            return datetime.datetime.fromisoformat(tree["__datetime__"])
        if "__date__" in tree:
            return datetime.date.fromisoformat(tree["__date__"])
        if "__time__" in tree:
            return datetime.time.fromisoformat(tree["__time__"])
        if "__decimal__" in tree:
            return decimal.Decimal(tree["__decimal__"])
        return {k: decode(v) for k, v in tree.items()}
    raise OpaqueValueError("unknown node type: {}".format(type(tree).__name__))


def contains_opaque(tree: Any) -> bool:
    """True if any node in the tree was recorded opaquely (or is otherwise
    not faithfully reconstructible as an input)."""
    if isinstance(tree, list):
        return any(contains_opaque(v) for v in tree)
    if isinstance(tree, dict):
        if any(k in tree for k in
               ("__opaque__", "__cycle__", "__adapted__", "__enum__",
                "__dataclass__")):
            return True
        return any(contains_opaque(v) for v in tree.values())
    return False


def canonical_json(tree: Any) -> str:
    """Deterministic JSON string of an encoded tree (used for ids/sorting)."""
    return json.dumps(tree, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)
