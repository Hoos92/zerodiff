"""Subprocess-isolated replay: crashes, hangs, and noisy stdout in the
rewrite become reported behavior instead of harness failures."""

import importlib
import sys
import textwrap

import pytest

import zerodiff
from zerodiff import differ
from zerodiff.config import Config
from zerodiff.replayer import replay_all


@pytest.fixture()
def iso_dir(tmp_path, monkeypatch):
    """Modules live in tmp_path; chdir there so the worker (which adds its
    cwd to sys.path) can import them too."""
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    importlib.invalidate_caches()
    yield tmp_path
    for name in list(sys.modules):
        if name.startswith(("isoleg_", "isonew_")):
            del sys.modules[name]


def _write(dir_path, name, source):
    (dir_path / (name + ".py")).write_text(textwrap.dedent(source),
                                           encoding="utf-8")
    importlib.invalidate_caches()


def _record(traces_dir, module_name, calls):
    zerodiff.wrap(module_name, "f")
    zerodiff.start_recording(str(traces_dir))
    try:
        module = importlib.import_module(module_name)
        for args, expect_raise in calls:
            if expect_raise:
                with pytest.raises(Exception):
                    module.f(*args)
            else:
                module.f(*args)
    finally:
        zerodiff.stop_recording()


def test_isolated_replay_matches_in_process(iso_dir):
    _write(iso_dir, "isoleg_a", """
        def f(x):
            if x < 0:
                raise ValueError("negative")
            return {"doubled": x * 2}
    """)
    _record(iso_dir / "traces", "isoleg_a", [((3,), False), ((-1,), True)])

    in_proc = replay_all(str(iso_dir / "traces"),
                         {"isoleg_a": "isoleg_a"}, Config())
    isolated = replay_all(str(iso_dir / "traces"),
                          {"isoleg_a": "isoleg_a"}, Config(), isolate=True)
    assert in_proc.matched == isolated.matched == 2
    assert not isolated.divergences


def test_crashing_rewrite_is_reported_not_fatal(iso_dir):
    _write(iso_dir, "isoleg_b", """
        def f(x):
            return x
    """)
    _write(iso_dir, "isonew_b", """
        import os

        def f(x):
            if x == 1:
                os._exit(3)   # simulates a segfault/native abort
            return x
    """)
    _record(iso_dir / "traces", "isoleg_b", [((1,), False), ((2,), False)])

    result = replay_all(str(iso_dir / "traces"),
                        {"isoleg_b": "isonew_b"}, Config(), isolate=True)
    crash = [d for d in result.divergences
             if d.kind == differ.KIND_CRASH]
    assert len(crash) == 1
    assert "exit code 3" in crash[0].hint or "exit code" in crash[0].hint
    # the worker restarted and the second trace still replayed fine
    assert result.matched == 1


def test_hanging_rewrite_times_out(iso_dir):
    _write(iso_dir, "isoleg_c", """
        def f(x):
            return x
    """)
    _write(iso_dir, "isonew_c", """
        import time

        def f(x):
            time.sleep(60)
            return x
    """)
    _record(iso_dir / "traces", "isoleg_c", [((5,), False)])

    result = replay_all(str(iso_dir / "traces"),
                        {"isoleg_c": "isonew_c"}, Config(),
                        isolate=True, timeout=1.5)
    assert len(result.divergences) == 1
    assert result.divergences[0].kind == differ.KIND_CRASH
    assert "hang" in result.divergences[0].hint


def test_noisy_stdout_does_not_corrupt_protocol(iso_dir):
    _write(iso_dir, "isoleg_d", """
        def f(x):
            return x + 1
    """)
    _write(iso_dir, "isonew_d", """
        def f(x):
            print("chatty rewrite prints stuff", x)
            return x + 1
    """)
    _record(iso_dir / "traces", "isoleg_d", [((1,), False), ((2,), False)])

    result = replay_all(str(iso_dir / "traces"),
                        {"isoleg_d": "isonew_d"}, Config(), isolate=True)
    assert result.matched == 2 and not result.divergences


def test_sysexit_in_rewrite_is_behavior_not_crash(iso_dir):
    _write(iso_dir, "isoleg_e", """
        def f(x):
            return x
    """)
    _write(iso_dir, "isonew_e", """
        import sys

        def f(x):
            sys.exit(2)   # raises SystemExit; catchable, so it's behavior
    """)
    _record(iso_dir / "traces", "isoleg_e", [((1,), False)])

    result = replay_all(str(iso_dir / "traces"),
                        {"isoleg_e": "isonew_e"}, Config(), isolate=True)
    assert len(result.divergences) == 1
    assert result.divergences[0].kind == differ.KIND_EXCEPTION
    assert "SystemExit" in str(result.divergences[0].actual)
