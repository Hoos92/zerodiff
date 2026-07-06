import importlib
import sys
import textwrap

import pytest

import nodrift
from nodrift import store
from nodrift.config import Config
from nodrift.replayer import map_target, replay_all, resolve_callable


@pytest.fixture()
def modules_dir(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    yield tmp_path
    # drop any modules the test created so names can be reused elsewhere
    for name in list(sys.modules):
        if name.startswith(("legmod_", "newmod_")):
            del sys.modules[name]


def _write_module(dir_path, name, source):
    (dir_path / (name + ".py")).write_text(textwrap.dedent(source),
                                           encoding="utf-8")
    importlib.invalidate_caches()


def test_record_and_replay_round_trip(modules_dir, tmp_path):
    _write_module(modules_dir, "legmod_a", """
        def double(x):
            if x < 0:
                raise ValueError("negative: %d" % x)
            return x * 2
    """)
    _write_module(modules_dir, "newmod_a", """
        def double(x):
            if x < 0:
                raise ValueError("negative: %d" % x)
            return x + x
    """)
    traces = str(tmp_path / "traces")
    nodrift.wrap("legmod_a", "double")
    nodrift.start_recording(traces)
    try:
        legmod = importlib.import_module("legmod_a")
        assert legmod.double(3) == 6
        assert legmod.double(0) == 0
        with pytest.raises(ValueError):
            legmod.double(-2)
    finally:
        nodrift.stop_recording()

    result = replay_all(traces, {"legmod_a": "newmod_a"}, Config())
    assert result.traces_total == 3
    assert result.matched == 3
    assert result.divergences == []


def test_replay_detects_divergence_and_missing_boundary(modules_dir, tmp_path):
    _write_module(modules_dir, "legmod_b", """
        def add(a, b):
            return a + b

        def sub(a, b):
            return a - b
    """)
    _write_module(modules_dir, "newmod_b", """
        def add(a, b):
            return a + b + 1
    """)
    traces = str(tmp_path / "traces")
    nodrift.wrap("legmod_b", "add")
    nodrift.wrap("legmod_b", "sub")
    nodrift.start_recording(traces)
    try:
        legmod = importlib.import_module("legmod_b")
        legmod.add(1, 2)
        legmod.sub(5, 3)
    finally:
        nodrift.stop_recording()

    result = replay_all(traces, {"legmod_b": "newmod_b"}, Config())
    kinds = sorted(d.kind for d in result.divergences)
    assert kinds == ["missing_boundary", "value_mismatch"]


def test_identical_calls_deduplicate(modules_dir, tmp_path):
    _write_module(modules_dir, "legmod_c", """
        def f(x):
            return x
    """)
    traces = str(tmp_path / "traces")
    nodrift.wrap("legmod_c", "f")
    nodrift.start_recording(traces)
    try:
        legmod = importlib.import_module("legmod_c")
        for _ in range(5):
            legmod.f(7)
        legmod.f(8)
    finally:
        nodrift.stop_recording()

    assert sum(1 for _ in store.iter_traces(traces)) == 6
    assert len(store.load_unique_traces(traces)) == 2


def test_recording_inactive_means_passthrough(modules_dir):
    _write_module(modules_dir, "legmod_d", """
        def f(x):
            return x * 10
    """)
    wrapped = nodrift.wrap("legmod_d", "f")
    assert wrapped(4) == 40  # no trace dir set; must just work


def test_kwargs_are_recorded_and_replayed(modules_dir, tmp_path):
    _write_module(modules_dir, "legmod_e", """
        def greet(name, punct="!"):
            return "hi " + name + punct
    """)
    _write_module(modules_dir, "newmod_e", """
        def greet(name, punct="!"):
            return "hi {}{}".format(name, punct)
    """)
    traces = str(tmp_path / "traces")
    nodrift.wrap("legmod_e", "greet")
    nodrift.start_recording(traces)
    try:
        legmod = importlib.import_module("legmod_e")
        legmod.greet("ada", punct="?")
        legmod.greet("bob")
    finally:
        nodrift.stop_recording()

    result = replay_all(traces, {"legmod_e": "newmod_e"}, Config())
    assert result.matched == 2 and not result.divergences


def test_unreplayable_opaque_input_is_skipped_not_hidden(modules_dir,
                                                         tmp_path):
    _write_module(modules_dir, "legmod_f", """
        def describe(obj):
            return str(type(obj).__name__)
    """)
    traces = str(tmp_path / "traces")
    nodrift.wrap("legmod_f", "describe")
    nodrift.start_recording(traces)
    try:
        legmod = importlib.import_module("legmod_f")
        legmod.describe(object())  # unserializable input
        legmod.describe("plain")   # replayable input
    finally:
        nodrift.stop_recording()

    result = replay_all(traces, {"legmod_f": "legmod_f"}, Config())
    assert len(result.skipped) == 1
    assert result.matched == 1
    summary = result.to_dict()["summary"]
    assert summary["skipped_unreplayable"] == 1


class TestMappingAndResolution:
    def test_longest_prefix_mapping(self):
        mappings = {"a": "x", "a.b": "y"}
        assert map_target("a.b.fn", mappings) == "y.fn"
        assert map_target("a.other.fn", mappings) == "x.other.fn"
        assert map_target("unmapped.fn", mappings) == "unmapped.fn"

    def test_resolve_module_function(self):
        fn, error = resolve_callable("os.path.join")
        import os.path
        assert fn is os.path.join and error is None

    def test_resolve_missing_returns_reason(self):
        fn, error = resolve_callable("os.path.not_a_function")
        assert fn is None and "no attribute" in error
        fn, error = resolve_callable("no_such_module_xyz.fn")
        assert fn is None and "no importable module" in error

    def test_resolve_broken_module_surfaces_import_error(self, tmp_path,
                                                         monkeypatch):
        monkeypatch.syspath_prepend(str(tmp_path))
        (tmp_path / "brokenmod_a.py").write_text(
            "from .nowhere import thing\n", encoding="utf-8")
        importlib.invalidate_caches()
        fn, error = resolve_callable("brokenmod_a.fn")
        assert fn is None
        assert "failed to import" in error and "brokenmod_a" in error
        sys.modules.pop("brokenmod_a", None)
