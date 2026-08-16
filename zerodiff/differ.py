"""Deep structural comparison of recorded vs replayed behavior.

Produces typed divergences with a path into the value and a hint written for
a coding agent, so a failed replay can be fixed in one iteration.
"""

from typing import Any, Dict, List, Optional, Tuple

MAX_DIVERGENCES_PER_TRACE = 25

KIND_VALUE = "value_mismatch"
KIND_TYPE = "type_mismatch"
KIND_EXCEPTION = "exception_mismatch"
KIND_MISSING = "missing_boundary"
KIND_WEAK = "weak_comparison"
KIND_REPLAY_ERROR = "replay_error"
KIND_CRASH = "process_crash"
KIND_TRUNCATED = "divergences_truncated"

# Kinds whose marker is shared by two Python types, told apart by a sibling
# flag: {"__set__": [...], "frozen": true}. The flag is part of the type, so
# it has to be compared -- comparing only the payload would call a set and a
# frozenset equivalent.
_FLAGGED_KINDS = {
    # kind: (flag key, type when the flag is set, type when it is not)
    "set": ("frozen", "frozenset", "set"),
    "bytes": ("mutable", "bytearray", "bytes"),
}

_MARKERS = ("__tuple__", "__set__", "__dict__", "__bytes__", "__datetime__",
            "__date__", "__time__", "__decimal__", "__enum__",
            "__dataclass__", "__float__", "__opaque__", "__adapted__",
            "__cycle__")

_MISSING = {"__missing__": True}


def _node_kind(tree: Any) -> str:
    if isinstance(tree, dict):
        for m in _MARKERS:
            if m in tree:
                return m.strip("_")
        return "dict"
    if isinstance(tree, bool):
        return "bool"
    if isinstance(tree, int):
        return "int"
    if isinstance(tree, float):
        return "float"
    if isinstance(tree, str):
        return "str"
    if isinstance(tree, list):
        return "list"
    if tree is None:
        return "None"
    return type(tree).__name__


def _preview(tree: Any, limit: int = 120) -> str:
    from .serializer import canonical_json

    if tree is _MISSING:
        return "<missing>"
    try:
        s = canonical_json(tree)
    except (TypeError, ValueError):
        s = repr(tree)
    return s if len(s) <= limit else s[:limit] + "..."


class Divergence:
    def __init__(self, kind: str, boundary: str, trace_id: str, path: str,
                 expected: Any, actual: Any, hint: str,
                 input_preview: str = "") -> None:
        self.kind = kind
        self.boundary = boundary
        self.trace_id = trace_id
        self.path = path
        self.expected = expected
        self.actual = actual
        self.hint = hint
        self.input_preview = input_preview

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "boundary": self.boundary,
            "trace_id": self.trace_id,
            "path": self.path,
            "input": self.input_preview,
            "expected": self.expected if self.expected is not _MISSING
            else "<missing>",
            "actual": self.actual if self.actual is not _MISSING
            else "<missing>",
            "hint": self.hint,
        }


def diff_output(expected: Dict[str, Any], actual: Dict[str, Any],
                boundary: str, trace_id: str, input_preview: str,
                float_tolerance: float = 0.0
                ) -> Tuple[List[Divergence], int]:
    """Compare recorded output vs replayed output (both already scrubbed).

    Returns (divergences, weak_match_count). weak_match_count counts opaque
    nodes whose digests matched -- comparisons ZeroDiff could not fully verify.
    """
    ctx = _Ctx(boundary, trace_id, input_preview, float_tolerance)

    exp_type = expected.get("type")
    act_type = actual.get("type")

    if exp_type == "exception" and act_type == "exception":
        exp_exc = expected.get("exception", {})
        act_exc = actual.get("exception", {})
        if exp_exc.get("type") != act_exc.get("type"):
            ctx.add(KIND_EXCEPTION, "output.exception.type",
                    exp_exc.get("type"), act_exc.get("type"),
                    "for input {inp}, the original raised {e} but the rewrite "
                    "raised {a} -- align the exception type in {b}.".format(
                        inp=input_preview, e=exp_exc.get("type"),
                        a=act_exc.get("type"), b=boundary))
        elif exp_exc.get("message") != act_exc.get("message"):
            ctx.add(KIND_EXCEPTION, "output.exception.message",
                    exp_exc.get("message"), act_exc.get("message"),
                    "same exception type ({e}) but a different message for "
                    "input {inp} -- callers matching on the message will "
                    "break; restore the original wording in {b}.".format(
                        e=exp_exc.get("type"), inp=input_preview, b=boundary))
        return ctx.finish()

    if exp_type == "exception" and act_type == "return":
        exp_exc = expected.get("exception", {})
        ctx.add(KIND_EXCEPTION, "output",
                "raise {}({!r})".format(exp_exc.get("type"),
                                        exp_exc.get("message")),
                "return " + _preview(actual.get("value")),
                "for input {inp}, the original raised {e}({m!r}) but the "
                "rewrite returned a value -- it silently accepts input the "
                "original rejected; restore the guard in {b}.".format(
                    inp=input_preview, e=exp_exc.get("type"),
                    m=exp_exc.get("message"), b=boundary))
        return ctx.finish()

    if exp_type == "return" and act_type == "exception":
        act_exc = actual.get("exception", {})
        ctx.add(KIND_EXCEPTION, "output",
                "return " + _preview(expected.get("value")),
                "raise {}({!r})".format(act_exc.get("type"),
                                        act_exc.get("message")),
                "for input {inp}, the original returned a value but the "
                "rewrite raised {e}({m!r}) -- the rewrite rejects input the "
                "original handled; fix {b} to handle this case.".format(
                    inp=input_preview, e=act_exc.get("type"),
                    m=act_exc.get("message"), b=boundary))
        return ctx.finish()

    _diff_tree(expected.get("value"), actual.get("value"), "output", ctx)
    return ctx.finish()


def diff_trees(expected: Any, actual: Any, path: str, boundary: str,
               trace_id: str, input_preview: str,
               float_tolerance: float = 0.0
               ) -> Tuple[List[Divergence], int]:
    """Compare two already-scrubbed encoded trees (used for argument
    mutations and other non-output comparisons)."""
    ctx = _Ctx(boundary, trace_id, input_preview, float_tolerance)
    _diff_tree(expected, actual, path, ctx)
    return ctx.finish()


class _Ctx:
    def __init__(self, boundary: str, trace_id: str, input_preview: str,
                 float_tolerance: float) -> None:
        self.boundary = boundary
        self.trace_id = trace_id
        self.input_preview = input_preview
        self.float_tolerance = float_tolerance
        self.divergences = []  # type: List[Divergence]
        self.weak_matches = 0
        self.truncated = False

    def full(self) -> bool:
        """At the cap, comparison stops descending -- so how many findings
        remain is genuinely unknown, only that some were dropped."""
        if len(self.divergences) >= MAX_DIVERGENCES_PER_TRACE:
            self.truncated = True
            return True
        return False

    def add(self, kind: str, path: str, expected: Any, actual: Any,
            hint: str) -> None:
        if self.full():
            return
        self.divergences.append(Divergence(
            kind, self.boundary, self.trace_id, path, expected, actual, hint,
            input_preview=self.input_preview))

    def finish(self) -> Tuple[List[Divergence], int]:
        # never drop findings silently: a capped trace says so in the report
        if self.truncated:
            self.divergences.append(Divergence(
                KIND_TRUNCATED, self.boundary, self.trace_id, "report",
                "an unknown number of further divergences",
                "%d shown" % len(self.divergences),
                "this single call hit the {cap}-divergence cap and "
                "comparison stopped, so more differences may remain -- fix "
                "the ones shown and re-run; capped traces usually share one "
                "root cause.".format(cap=MAX_DIVERGENCES_PER_TRACE),
                input_preview=self.input_preview))
        return self.divergences, self.weak_matches


def _diff_tree(exp: Any, act: Any, path: str, ctx: _Ctx) -> None:
    if ctx.full():
        return

    exp_kind = _node_kind(exp)
    act_kind = _node_kind(act)

    # opaque nodes: compare digests, count weak matches
    if exp_kind == "opaque" or act_kind == "opaque":
        if exp_kind == "opaque" and act_kind == "opaque":
            e, a = exp["__opaque__"], act["__opaque__"]
            if e.get("digest") == a.get("digest"):
                ctx.weak_matches += 1
            else:
                ctx.add(KIND_WEAK, path, e.get("repr"), a.get("repr"),
                        "at {p}, values of type {t} could not be fully "
                        "serialized and their fingerprints differ for input "
                        "{inp} -- inspect {b} manually; ZeroDiff can see the "
                        "change but not explain it.".format(
                            p=path, t=e.get("type"), inp=ctx.input_preview,
                            b=ctx.boundary))
        else:
            ctx.add(KIND_TYPE, path, _preview(exp), _preview(act),
                    "at {p}, the original produced {ek} but the rewrite "
                    "produced {ak} for input {inp} -- align the return "
                    "structure in {b}.".format(
                        p=path, ek=exp_kind, ak=act_kind,
                        inp=ctx.input_preview, b=ctx.boundary))
        return

    if exp_kind != act_kind:
        # int/float with tolerance is still a type change worth knowing about
        ctx.add(KIND_TYPE, path, _preview(exp), _preview(act),
                "at {p}, expected {ek} but got {ak} for input {inp} -- e.g. "
                "returning a list where the original returned a tuple, or a "
                "str where it returned an int; make {b} preserve the exact "
                "type.".format(p=path, ek=exp_kind, ak=act_kind,
                               inp=ctx.input_preview, b=ctx.boundary))
        return

    if exp_kind == "float":
        # nan/inf are encoded as {"__float__": "nan"} markers; a marker on
        # either side means no arithmetic tolerance applies
        if isinstance(exp, dict) or isinstance(act, dict):
            if exp != act:
                ctx.add(KIND_VALUE, path, _preview(exp), _preview(act),
                        "at {p}, expected {e} but got {a} for input {inp} -- "
                        "non-finite float behavior changed in {b}.".format(
                            p=path, e=_preview(exp), a=_preview(act),
                            inp=ctx.input_preview, b=ctx.boundary))
            return
        if exp != act:
            tol = ctx.float_tolerance
            if tol > 0 and abs(exp - act) <= tol:
                return
            ctx.add(KIND_VALUE, path, exp, act,
                    "at {p}, expected {e!r} but got {a!r} for input {inp} "
                    "(difference {d:g}) -- check rounding/precision in {b}; "
                    "if this difference is acceptable noise, set "
                    "float_tolerance in zerodiff.toml.".format(
                        p=path, e=exp, a=act, d=abs(exp - act),
                        inp=ctx.input_preview, b=ctx.boundary))
        return

    if exp_kind in ("bool", "int", "str", "None"):
        if exp != act:
            ctx.add(KIND_VALUE, path, exp, act,
                    "at {p}, expected {e!r} but got {a!r} for input {inp} -- "
                    "fix the logic in {b} that computes this value.".format(
                        p=path, e=exp, a=act, inp=ctx.input_preview,
                        b=ctx.boundary))
        return

    if exp_kind == "list":
        if len(exp) != len(act):
            ctx.add(KIND_VALUE, path + ".length", len(exp), len(act),
                    "at {p}, the original produced {e} items but the rewrite "
                    "produced {a} for input {inp} -- an item is being "
                    "dropped, duplicated, or added in {b}.".format(
                        p=path, e=len(exp), a=len(act),
                        inp=ctx.input_preview, b=ctx.boundary))
        for i in range(min(len(exp), len(act))):
            _diff_tree(exp[i], act[i], "%s[%d]" % (path, i), ctx)
        return

    if exp_kind == "dict":
        exp_keys, act_keys = set(exp), set(act)
        for key in sorted(exp_keys - act_keys):
            ctx.add(KIND_TYPE, "%s.%s" % (path, key), _preview(exp[key]),
                    _MISSING,
                    "at {p}, key {k!r} exists in the original output but is "
                    "missing from the rewrite's for input {inp} -- add it "
                    "back in {b}.".format(p=path, k=key,
                                          inp=ctx.input_preview,
                                          b=ctx.boundary))
        for key in sorted(act_keys - exp_keys):
            ctx.add(KIND_TYPE, "%s.%s" % (path, key), _MISSING,
                    _preview(act[key]),
                    "at {p}, the rewrite adds key {k!r} that the original "
                    "output does not have for input {inp} -- remove it from "
                    "{b} (extra fields change the observable "
                    "behavior).".format(p=path, k=key, inp=ctx.input_preview,
                                        b=ctx.boundary))
        for key in sorted(exp_keys & act_keys):
            _diff_tree(exp[key], act[key], "%s.%s" % (path, key), ctx)
        return

    # marker containers: recurse into their payloads
    marker = "__%s__" % exp_kind
    exp_payload, act_payload = exp.get(marker), act.get(marker)

    # a sibling flag distinguishes two types sharing one marker; equal
    # payloads with different flags are still a behavior change
    flagged = _FLAGGED_KINDS.get(exp_kind)
    if flagged is not None:
        flag, when_set, when_clear = flagged
        exp_type = when_set if exp.get(flag) else when_clear
        act_type = when_set if act.get(flag) else when_clear
        if exp_type != act_type:
            ctx.add(KIND_TYPE, path, exp_type, act_type,
                    "at {p}, the original produced a {e} but the rewrite "
                    "produced a {a} for input {inp} -- the contents are the "
                    "same but the type and its mutability are not; return a "
                    "{e} from {b}.".format(p=path, e=exp_type, a=act_type,
                                           inp=ctx.input_preview,
                                           b=ctx.boundary))
            return

    if exp_kind in ("tuple", "set", "dict"):
        _diff_tree(exp_payload, act_payload, path, ctx)
        return

    # dataclasses and enums recurse field-by-field so that float_tolerance
    # applies inside them and hints point at the field that actually changed
    if exp_kind == "dataclass":
        exp_info, act_info = exp[marker], act[marker]
        if exp_info.get("type") != act_info.get("type"):
            ctx.add(KIND_TYPE, path, exp_info.get("type"),
                    act_info.get("type"),
                    "at {p}, the original produced a {e} but the rewrite "
                    "produced a {a} for input {inp} -- return the same "
                    "dataclass from {b}.".format(
                        p=path, e=exp_info.get("type"),
                        a=act_info.get("type"), inp=ctx.input_preview,
                        b=ctx.boundary))
            return
        _diff_tree(exp_info.get("fields"), act_info.get("fields"), path, ctx)
        return

    if exp_kind == "enum":
        exp_info, act_info = exp[marker], act[marker]
        if exp_info.get("type") != act_info.get("type"):
            ctx.add(KIND_TYPE, path, exp_info.get("type"),
                    act_info.get("type"),
                    "at {p}, the original produced a {e} member but the "
                    "rewrite produced a {a} for input {inp} -- return the "
                    "same enum from {b}.".format(
                        p=path, e=exp_info.get("type"),
                        a=act_info.get("type"), inp=ctx.input_preview,
                        b=ctx.boundary))
            return
        if exp_info.get("name") != act_info.get("name"):
            ctx.add(KIND_VALUE, path, exp_info.get("name"),
                    act_info.get("name"),
                    "at {p}, expected enum member {e} but got {a} for input "
                    "{inp} -- fix the logic in {b} that selects the "
                    "member.".format(p=path, e=exp_info.get("name"),
                                     a=act_info.get("name"),
                                     inp=ctx.input_preview, b=ctx.boundary))
            return
        _diff_tree(exp_info.get("value"), act_info.get("value"),
                   path + ".value", ctx)
        return

    if exp_payload != act_payload:
        ctx.add(KIND_VALUE, path, _preview(exp), _preview(act),
                "at {p}, expected {e} but got {a} for input {inp} -- fix the "
                "logic in {b}.".format(p=path, e=_preview(exp),
                                       a=_preview(act),
                                       inp=ctx.input_preview,
                                       b=ctx.boundary))
