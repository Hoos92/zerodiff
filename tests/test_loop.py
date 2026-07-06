"""The agent feedback loop, driven by a scripted fake agent."""

import importlib
import sys
import textwrap

import pytest

import nodrift
from nodrift.config import Config
from nodrift.loop import build_prompt, run_loop

LEGACY = """
def add_fee(amount):
    if amount < 0:
        raise ValueError("amount must be positive")
    return round(amount * 1.05, 2)
"""

BUGGY_REWRITE = """
def add_fee(amount):
    if amount < 0:
        return 0
    return round(amount * 1.05, 2)
"""

FIXED_REWRITE = """
def add_fee(amount):
    if amount < 0:
        raise ValueError("amount must be positive")
    return round(amount * 1.05, 2)
"""

# a stand-in for a coding agent: reads the prompt, applies the fix
FIX_AGENT = """
import pathlib
import sys

prompt = sys.stdin.read() if len(sys.argv) < 2 else \\
    pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
assert "divergence" in prompt.lower() or "Divergences" in prompt
assert "add_fee" in prompt
pathlib.Path("loopnew_a.py").write_text({fixed!r}, encoding="utf-8")
"""

DO_NOTHING_AGENT = "import sys; sys.stdin.read()\n"


@pytest.fixture()
def loop_dir(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    importlib.invalidate_caches()
    yield tmp_path
    for name in list(sys.modules):
        if name.startswith(("loopleg_", "loopnew_")):
            del sys.modules[name]


def _record_legacy(tmp_path):
    (tmp_path / "loopleg_a.py").write_text(textwrap.dedent(LEGACY),
                                           encoding="utf-8")
    importlib.invalidate_caches()
    nodrift.wrap("loopleg_a", "add_fee")
    nodrift.start_recording(str(tmp_path / "traces"))
    try:
        module = importlib.import_module("loopleg_a")
        module.add_fee(100)
        module.add_fee(0)
        try:
            module.add_fee(-5)
        except ValueError:
            pass
    finally:
        nodrift.stop_recording()


def test_loop_converges_with_stdin_agent(loop_dir):
    _record_legacy(loop_dir)
    (loop_dir / "loopnew_a.py").write_text(textwrap.dedent(BUGGY_REWRITE),
                                           encoding="utf-8")
    (loop_dir / "fix_agent.py").write_text(
        textwrap.dedent(FIX_AGENT).format(fixed=textwrap.dedent(
            FIXED_REWRITE)), encoding="utf-8")

    remaining = run_loop(
        str(loop_dir / "traces"), {"loopleg_a": "loopnew_a"}, Config(),
        agent_cmd='"{}" fix_agent.py'.format(sys.executable),
        max_iters=3, workdir=str(loop_dir))
    assert remaining == 0


def test_loop_converges_with_prompt_file_agent(loop_dir):
    _record_legacy(loop_dir)
    (loop_dir / "loopnew_a.py").write_text(textwrap.dedent(BUGGY_REWRITE),
                                           encoding="utf-8")
    (loop_dir / "fix_agent.py").write_text(
        textwrap.dedent(FIX_AGENT).format(fixed=textwrap.dedent(
            FIXED_REWRITE)), encoding="utf-8")

    remaining = run_loop(
        str(loop_dir / "traces"), {"loopleg_a": "loopnew_a"}, Config(),
        agent_cmd='"{}" fix_agent.py {{prompt_file}}'.format(sys.executable),
        max_iters=3, workdir=str(loop_dir))
    assert remaining == 0


def test_loop_gives_up_after_max_iters(loop_dir):
    _record_legacy(loop_dir)
    (loop_dir / "loopnew_a.py").write_text(textwrap.dedent(BUGGY_REWRITE),
                                           encoding="utf-8")
    (loop_dir / "noop_agent.py").write_text(DO_NOTHING_AGENT,
                                            encoding="utf-8")

    remaining = run_loop(
        str(loop_dir / "traces"), {"loopleg_a": "loopnew_a"}, Config(),
        agent_cmd='"{}" noop_agent.py'.format(sys.executable),
        max_iters=2, workdir=str(loop_dir))
    assert remaining > 0


def test_prompt_contains_actionable_content():
    report = {
        "divergences": [{
            "kind": "exception_mismatch", "boundary": "m.f", "path": "output",
            "input": "(-5)", "expected": "raise ValueError",
            "actual": "return 0", "hint": "restore the guard in m.f",
        }],
        "mappings": {"m": "m2"},
    }
    prompt = build_prompt(report)
    assert "restore the guard" in prompt
    assert "(-5)" in prompt
    assert "m -> m2" in prompt
    assert "Do not \"improve\" behavior" in prompt
