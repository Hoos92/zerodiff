import importlib
import json
import os
import subprocess
import sys
import textwrap

import pytest

from nodrift import store
from nodrift.autohook import instrument_module, matches
from nodrift.config import Config
from nodrift.replayer import replay_all


class TestMatches:
    def test_exact(self):
        assert matches("billing", ["billing"])

    def test_submodule_of_pattern(self):
        assert matches("billing.pricing", ["billing"])

    def test_glob(self):
        assert matches("billing.pricing", ["billing.*"])
        assert not matches("shipping.rates", ["billing.*"])

    def test_no_prefix_string_match(self):
        assert not matches("billingx", ["billing"])


class TestInstrumentModule:
    def _make_module(self, tmp_path, monkeypatch, name, source):
        (tmp_path / (name + ".py")).write_text(textwrap.dedent(source),
                                               encoding="utf-8")
        monkeypatch.syspath_prepend(str(tmp_path))
        importlib.invalidate_caches()
        module = importlib.import_module(name)
        yield_cleanup = lambda: sys.modules.pop(name, None)  # noqa: E731
        return module, yield_cleanup

    def test_wraps_public_functions_only(self, tmp_path, monkeypatch):
        module, cleanup = self._make_module(tmp_path, monkeypatch,
                                            "instmod_a", """
            import os

            CONST = 5

            def public(x):
                return x

            def _private(x):
                return x

            class Thing:
                def method(self):
                    return 1
        """)
        try:
            count = instrument_module(module)
            assert count == 1
            assert getattr(module.public, "__nodrift_wrapped__", None) \
                is not None
            assert getattr(module._private, "__nodrift_wrapped__", None) \
                is None
            # imported names must not be wrapped
            assert getattr(module.os.path.join, "__nodrift_wrapped__",
                           None) is None
        finally:
            cleanup()

    def test_idempotent(self, tmp_path, monkeypatch):
        module, cleanup = self._make_module(tmp_path, monkeypatch,
                                            "instmod_b", """
            def f(x):
                return x
        """)
        try:
            assert instrument_module(module) == 1
            assert instrument_module(module) == 0
        finally:
            cleanup()


def test_record_include_needs_no_source_edits(tmp_path):
    """End to end: plain legacy module + plain driver, recorded via
    --include with zero nodrift imports anywhere in user code."""
    (tmp_path / "autolegmod.py").write_text(textwrap.dedent("""
        def triple(x):
            if x < 0:
                raise ValueError("negative")
            return x * 3

        def _helper(x):
            return x
    """), encoding="utf-8")
    (tmp_path / "plainrun.py").write_text(textwrap.dedent("""
        import autolegmod

        print(autolegmod.triple(2))
        print(autolegmod.triple(0))
        try:
            autolegmod.triple(-1)
        except ValueError:
            pass
        autolegmod._helper(9)
    """), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, "-m", "nodrift.cli", "record", "-o", "traces",
         "--include", "autolegmod", "--", sys.executable, "plainrun.py"],
        cwd=str(tmp_path), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "recorded 3 calls across 1 boundaries" in proc.stdout

    traces = list(store.iter_traces(str(tmp_path / "traces")))
    targets = {t["boundary"]["target"] for t in traces}
    assert targets == {"autolegmod.triple"}
    assert any(t["output"]["type"] == "exception" for t in traces)

    # replay the auto-recorded traces against the same module
    sys.path.insert(0, str(tmp_path))
    try:
        result = replay_all(str(tmp_path / "traces"),
                            {"autolegmod": "autolegmod"}, Config())
        assert result.matched == 3 and not result.divergences
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("autolegmod", None)


def test_include_pythonpath_is_preserved(tmp_path):
    """--include must prepend, not replace, an existing PYTHONPATH."""
    dep_dir = tmp_path / "deps"
    dep_dir.mkdir()
    (dep_dir / "extdep.py").write_text("VALUE = 41\n", encoding="utf-8")
    (tmp_path / "legmod2.py").write_text(textwrap.dedent("""
        import extdep

        def get(x):
            return extdep.VALUE + x
    """), encoding="utf-8")
    (tmp_path / "run2.py").write_text(
        "import legmod2\nprint(legmod2.get(1))\n", encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(dep_dir)
    proc = subprocess.run(
        [sys.executable, "-m", "nodrift.cli", "record", "-o", "traces",
         "--include", "legmod2", "--", sys.executable, "run2.py"],
        cwd=str(tmp_path), capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "42" in proc.stdout
