"""v0.13.0 correctness fixes found by auditing the comparison core.

The first three cases were *false matches*: ZeroDiff reported "matched" for
values that behave differently. For a verification harness those are the
worst possible defect, so each one is pinned here.
"""

import dataclasses
import enum
import importlib
import sys
import textwrap

import pytest

import zerodiff
from zerodiff import differ, replayer, scrubbers, store
from zerodiff.agent import AgentError, BuiltinAgent
from zerodiff.config import Config
from zerodiff.quality import check_source
from zerodiff.serializer import RESERVED_KEYS, canonical_json, decode, encode


def _diff(a, b, tol=0.0):
    return differ.diff_trees(encode(a), encode(b), "output", "m.f", "t1",
                             "(x)", float_tolerance=tol)


def _kinds(divs):
    return [d.kind for d in divs]


class TestFalseMatches:
    """Values whose difference the differ used to swallow entirely."""

    def test_frozenset_is_not_a_set(self):
        divs, _ = _diff(frozenset([1, 2]), {1, 2})
        assert _kinds(divs) == [differ.KIND_TYPE]
        assert "frozenset" in divs[0].hint

    def test_bytes_is_not_a_bytearray(self):
        divs, _ = _diff(b"ab", bytearray(b"ab"))
        assert _kinds(divs) == [differ.KIND_TYPE]
        assert "bytearray" in divs[0].hint

    @pytest.mark.parametrize("same", [
        (frozenset([1, 2]), frozenset([2, 1])),
        ({1, 2}, {2, 1}),
        (b"ab", b"ab"),
        (bytearray(b"ab"), bytearray(b"ab")),
    ])
    def test_matching_flag_still_matches(self, same):
        divs, _ = _diff(*same)
        assert divs == []

    def test_dict_cannot_impersonate_the_type_it_names(self):
        # {"__tuple__": [1, 2]} once encoded byte-identically to (1, 2)
        assert canonical_json(encode({"__tuple__": [1, 2]})) != \
            canonical_json(encode((1, 2)))
        divs, _ = _diff({"__tuple__": [1, 2]}, (1, 2))
        assert _kinds(divs) == [differ.KIND_TYPE]

    @pytest.mark.parametrize("key", sorted(RESERVED_KEYS))
    def test_reserved_keys_round_trip_as_dicts(self, key):
        original = {key: [1, 2]}
        assert decode(encode(original)) == original

    def test_ordinary_string_keys_keep_the_compact_encoding(self):
        assert encode({"a": 1, "b": 2}) == {"a": 1, "b": 2}


class TestToleranceAndHints:
    def test_float_tolerance_applies_inside_a_dataclass(self):
        @dataclasses.dataclass
        class Point:
            v: float

        assert _diff(Point(1.0000001), Point(1.0), tol=1e-6)[0] == []
        assert _diff(Point(1.5), Point(2.5), tol=1e-6)[0] != []

    def test_dataclass_hint_names_the_field_that_changed(self):
        @dataclasses.dataclass
        class Point:
            v: float
            n: str = "x"

        divs, _ = _diff(Point(1.0), Point(2.0))
        assert divs[0].path == "output.v"  # not the whole blob at "output"

    def test_enum_divergence_names_the_member(self):
        class Color(enum.Enum):
            RED = 1
            BLUE = 2

        divs, _ = _diff(Color.RED, Color.BLUE)
        assert _kinds(divs) == [differ.KIND_VALUE]
        assert "RED" in str(divs[0].expected)
        assert _diff(Color.RED, Color.RED)[0] == []


class TestOpaqueScrubbing:
    """A scrubbed repr has to be re-fingerprinted; otherwise the stale
    digest reports two now-identical reprs as differing."""

    class Ticket:
        def __init__(self, ts):
            self.ts = ts

        def __repr__(self):
            return "<Ticket created=%s>" % self.ts

    def _scrubbed(self, value, builtins_):
        plan = scrubbers.compile_scrubbers(
            Config({"scrub": {"builtin": builtins_}}), "m.f")
        return scrubbers.scrub(encode(value), plan["ignore_fields"],
                               plan["regexes"])

    def test_configured_scrubber_silences_opaque_noise(self):
        a = self._scrubbed(self.Ticket("2024-01-01T00:00:00"), ["timestamp"])
        b = self._scrubbed(self.Ticket("2024-06-15T12:30:00"), ["timestamp"])
        divs, weak = differ.diff_trees(a, b, "output", "m.f", "t1", "(x)")
        assert divs == [] and weak == 1

    def test_real_opaque_difference_still_reported(self):
        a = self._scrubbed(self.Ticket("alpha"), ["timestamp"])
        b = self._scrubbed(self.Ticket("beta"), ["timestamp"])
        divs, _ = differ.diff_trees(a, b, "output", "m.f", "t1", "(x)")
        assert _kinds(divs) == [differ.KIND_WEAK]


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    importlib.invalidate_caches()
    yield tmp_path
    for name in list(sys.modules):
        if name.startswith("v13"):
            del sys.modules[name]


class TestInstrumentationLifecycle:
    def test_record_class_is_idempotent(self, ws):
        (ws / "v13cls.py").write_text(textwrap.dedent("""
            class C:
                @staticmethod
                def s(x):
                    return x

                @classmethod
                def c(cls, x):
                    return x
        """), encoding="utf-8")
        importlib.invalidate_caches()
        assert zerodiff.record_class("v13cls", "C") == 2
        # a second call must not wrap the wrapper: that recorded two traces
        # per call and inflated the behavior count
        assert zerodiff.record_class("v13cls", "C") == 0

        zerodiff.start_recording(str(ws / "traces"))
        try:
            module = importlib.import_module("v13cls")
            module.C.s(1)
            module.C.c(1)
        finally:
            zerodiff.stop_recording()
        assert len(list(store.iter_traces(str(ws / "traces")))) == 2

    def test_unwrap_restores_the_original(self, ws):
        (ws / "v13fn.py").write_text("def f(x):\n    return x\n",
                                     encoding="utf-8")
        importlib.invalidate_caches()
        zerodiff.wrap("v13fn", "f")
        assert zerodiff.unwrap("v13fn", "f") is True
        assert zerodiff.unwrap("v13fn", "f") is False  # nothing left to undo

        zerodiff.start_recording(str(ws / "traces"))
        try:
            importlib.import_module("v13fn").f(1)
        finally:
            zerodiff.stop_recording()
        assert not (ws / "traces").exists()  # nothing was recorded

    def test_unwrap_class_restores_every_descriptor(self, ws):
        (ws / "v13cls2.py").write_text(textwrap.dedent("""
            class C:
                @staticmethod
                def s(x):
                    return x

                def m(self, x):
                    return x
        """), encoding="utf-8")
        importlib.invalidate_caches()
        assert zerodiff.record_class("v13cls2", "C") == 2
        assert zerodiff.unwrap_class("v13cls2", "C") == 2
        assert zerodiff.unwrap_class("v13cls2", "C") == 0


class TestReplayAccounting:
    def test_harness_error_counts_the_trace_once(self, monkeypatch):
        trace = {"id": "t1", "boundary": {"kind": "function",
                                          "target": "m.f"},
                 "input": {"args": [1], "kwargs": {}},
                 "output": {"type": "return", "value": 1},
                 "meta": {"py": "3.8.0", "seq": 0}}

        class Invoker:
            def invoke(self, target, encoded_input):
                return {"status": "ok",
                        "output": {"type": "return", "value": 1}}

            def close(self):
                pass

        def boom(*args, **kwargs):
            raise RuntimeError("harness bug")

        monkeypatch.setattr(differ, "diff_output", boom)
        result = replayer._replay_traces([trace], {}, Config(), Invoker())
        summary = result.to_dict()["summary"]
        assert summary["replayed"] == summary["traces_total"] == 1
        assert summary["boundaries"]["m.f"]["replayed"] == 1

    def test_in_order_follows_seq_not_the_wall_clock(self, ws):
        trace_dir = str(ws / "traces")
        for seq, ts in ((0, "2024-01-01T00:00:02"),
                        (1, "2024-01-01T00:00:00")):  # clock stepped back
            store.append_trace(trace_dir, {
                "schema": store.SCHEMA_VERSION, "id": "t%d" % seq,
                "boundary": {"kind": "function", "target": "m.f"},
                "input": {"args": [seq], "kwargs": {}},
                "output": {"type": "return", "value": seq},
                "meta": {"seq": seq, "ts": ts, "py": "3.8.0"}})
        traces = list(store.iter_traces(trace_dir))
        traces.sort(key=lambda t: (t.get("meta", {}).get("seq", 0),
                                   t.get("meta", {}).get("ts", "")))
        assert [t["meta"]["seq"] for t in traces] == [0, 1]


class TestQualityGateImportForms:
    """Rules are written against canonical dotted names, but these are the
    spellings people and LLMs actually produce."""

    @pytest.mark.parametrize("source,rule", [
        ("import os\nos.system('ls')\n", "shell-injection"),
        ("from os import system\nsystem('ls')\n", "shell-injection"),
        ("import os as o\no.system('ls')\n", "shell-injection"),
        ("from os import system as s\ns('ls')\n", "shell-injection"),
        ("from subprocess import run\nrun('ls', shell=True)\n",
         "shell-injection"),
        ("from pickle import loads\nloads(b'')\n",
         "unsafe-deserialization"),
        ("from yaml import load\nload('x')\n", "unsafe-deserialization"),
        ("from tempfile import mktemp\nmktemp()\n", "insecure-tempfile"),
    ])
    def test_blocked_however_it_is_imported(self, source, rule):
        errors = [f for f in check_source(source, "x.py")
                  if f.severity == "error"]
        assert [f.rule for f in errors] == [rule]

    @pytest.mark.parametrize("source", [
        "import os.path\nos.path.join('a', 'b')\n",
        "def loads(x):\n    return x\n\n\nloads(1)\n",
        "from json import loads\nloads('{}')\n",
    ])
    def test_benign_code_is_not_flagged(self, source):
        assert [f for f in check_source(source, "x.py")
                if f.severity == "error"] == []


class TestAgentResponseRobustness:
    """`openai-compatible` targets third-party servers; a surprising payload
    must fail the iteration, not crash the loop with a traceback."""

    @pytest.mark.parametrize("payload", [
        {"choices": []},
        {"choices": [{"text": "no message key"}]},
        {"unexpected": True},
    ])
    def test_malformed_response_raises_agent_error(self, payload):
        agent = BuiltinAgent("openai-compatible:m",
                             base_url="http://127.0.0.1:1/v1")
        with pytest.raises(AgentError):
            agent._parse_response(payload)

    def test_well_formed_response_still_parses(self):
        agent = BuiltinAgent("openai-compatible:m",
                             base_url="http://127.0.0.1:1/v1")
        assert agent._parse_response(
            {"choices": [{"message": {"content": "hi"}}]}) == "hi"
