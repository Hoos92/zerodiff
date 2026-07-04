"""v0.8.0 architecture hardening: mutation capture, in-order replay,
loop stall/timeout, parallel replay, MCP quality, attestation coherence."""

import importlib
import json
import subprocess
import sys
import textwrap
import time

import pytest

import retrace
from retrace import cli, differ, enterprise, recorder, report as report_mod
from retrace.config import Config, _parse_toml_subset
from retrace.loop import build_prompt, run_loop
from retrace.replayer import replay_all


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(recorder, "_config", None)
    importlib.invalidate_caches()
    yield tmp_path
    monkeypatch.setattr(recorder, "_config", None)
    for name in list(sys.modules):
        if name.startswith(("v8leg_", "v8new_", "v8state_")):
            del sys.modules[name]


def _write(ws_dir, name, source):
    (ws_dir / (name + ".py")).write_text(textwrap.dedent(source),
                                         encoding="utf-8")
    importlib.invalidate_caches()


MUTATING_LEGACY = """
    def register(items, tag):
        items.append(tag)
        return len(items)
"""

NON_MUTATING_REWRITE = """
    def register(items, tag):
        return len(items) + 1   # same return value, forgets to mutate!
"""


class TestMutationCapture:
    def _record(self, ws_dir):
        _write(ws_dir, "v8leg_m", MUTATING_LEGACY)
        retrace.wrap("v8leg_m", "register")
        retrace.start_recording(str(ws_dir / "traces"))
        try:
            importlib.import_module("v8leg_m").register(["a", "b"], "c")
        finally:
            retrace.stop_recording()

    def test_mutation_recorded(self, ws):
        self._record(ws)
        trace_file = next((ws / "traces").glob("*.jsonl"))
        trace = json.loads(trace_file.read_text(encoding="utf-8"))
        assert trace["mutations"]["0"] == ["a", "b", "c"]
        assert "seq" in trace["meta"]

    def test_faithful_rewrite_passes(self, ws):
        self._record(ws)
        _write(ws, "v8new_m", MUTATING_LEGACY)
        result = replay_all(str(ws / "traces"), {"v8leg_m": "v8new_m"},
                            Config())
        assert result.matched == 1 and not result.divergences

    def test_non_mutating_rewrite_is_caught(self, ws):
        self._record(ws)
        _write(ws, "v8new_m", NON_MUTATING_REWRITE)
        result = replay_all(str(ws / "traces"), {"v8leg_m": "v8new_m"},
                            Config())
        assert len(result.divergences) >= 1
        d = result.divergences[0]
        assert d.path.startswith("mutation.args[0]")
        assert "modified this argument in place" in d.hint

    def test_non_mutating_rewrite_caught_isolated_too(self, ws):
        self._record(ws)
        _write(ws, "v8new_m", NON_MUTATING_REWRITE)
        result = replay_all(str(ws / "traces"), {"v8leg_m": "v8new_m"},
                            Config(), isolate=True)
        assert any(d.path.startswith("mutation.") for d in result.divergences)

    def test_opt_out_disables_capture(self, ws, monkeypatch):
        (ws / "retrace.toml").write_text("[record]\nmutations = false\n",
                                         encoding="utf-8")
        monkeypatch.setattr(recorder, "_config", None)
        self._record(ws)
        trace_file = next((ws / "traces").glob("*.jsonl"))
        trace = json.loads(trace_file.read_text(encoding="utf-8"))
        assert "mutations" not in trace


STATEFUL = """
    state = []

    def push(x):
        state.append(x)
        return list(state)

    def total():
        return len(state)
"""


class TestInOrderReplay:
    def _record_interleaved(self, ws_dir):
        _write(ws_dir, "v8state_a", STATEFUL)
        retrace.wrap("v8state_a", "push")
        retrace.wrap("v8state_a", "total")
        retrace.start_recording(str(ws_dir / "traces"))
        try:
            module = importlib.import_module("v8state_a")
            module.push(1)
            module.total()   # -> 1
            module.push(2)
            module.total()   # -> 2 (same input, different output!)
        finally:
            retrace.stop_recording()

    def test_in_order_replays_chronologically(self, ws):
        self._record_interleaved(ws)
        _write(ws, "v8new_s", STATEFUL)
        result = replay_all(str(ws / "traces"), {"v8state_a": "v8new_s"},
                            Config(), in_order=True)
        assert result.replayed == 4
        assert result.matched == 4, [d.to_dict() for d in result.divergences]

    def test_unordered_replay_diverges_on_stateful_code(self, ws):
        self._record_interleaved(ws)
        _write(ws, "v8new_s2", STATEFUL)
        result = replay_all(str(ws / "traces"), {"v8state_a": "v8new_s2"},
                            Config())
        assert result.diverged_traces >= 1  # why --in-order exists

    def test_jobs_and_in_order_are_mutually_exclusive(self, ws, capsys):
        self._record_interleaved(ws)
        code = cli.main(["replay", "-t", "traces", "--jobs", "2",
                         "--in-order"])
        assert code == 2
        assert "incompatible" in capsys.readouterr().err


class TestLoopRobustness:
    def _record_simple(self, ws_dir):
        _write(ws_dir, "v8leg_l", "def f(x):\n    return x * 2\n")
        retrace.wrap("v8leg_l", "f")
        retrace.start_recording(str(ws_dir / "traces"))
        try:
            importlib.import_module("v8leg_l").f(5)
        finally:
            retrace.stop_recording()
        _write(ws_dir, "v8new_l", "def f(x):\n    return x * 3\n")

    def test_stall_detection_stops_early(self, ws):
        self._record_simple(ws)
        (ws / "agent.py").write_text(
            "import sys, pathlib\n"
            "sys.stdin.read()\n"
            "log = pathlib.Path('invocations.txt')\n"
            "log.write_text(log.read_text() + 'x' if log.exists() else 'x')\n",
            encoding="utf-8")
        remaining = run_loop(str(ws / "traces"), {"v8leg_l": "v8new_l"},
                             Config(),
                             '"{}" agent.py'.format(sys.executable),
                             max_iters=6, workdir=str(ws))
        assert remaining > 0
        # stall detected after 2 identical iterations -> agent ran once
        assert (ws / "invocations.txt").read_text() == "x"

    def test_agent_timeout_stops_loop(self, ws):
        self._record_simple(ws)
        (ws / "slow_agent.py").write_text(
            "import time, sys\nsys.stdin.read()\ntime.sleep(60)\n",
            encoding="utf-8")
        start = time.time()
        remaining = run_loop(str(ws / "traces"), {"v8leg_l": "v8new_l"},
                             Config(),
                             '"{}" slow_agent.py'.format(sys.executable),
                             max_iters=4, workdir=str(ws),
                             agent_timeout=3.0)
        assert remaining > 0
        assert time.time() - start < 40

    def test_prompt_names_files_and_attempt(self):
        report = {"divergences": [
            {"kind": "value_mismatch", "boundary": "m.f", "path": "output",
             "input": "(1)", "expected": "2", "actual": "3",
             "hint": "fix it"}], "mappings": {"m": "m2"}}
        prompt = build_prompt(report, files=["m2.py"], iteration=2,
                              max_iters=5)
        assert "m2.py" in prompt
        assert "attempt 2 of 5" in prompt


def test_parallel_replay_matches_serial(ws):
    _write(ws, "v8leg_p", "def f(x):\n    return x + 1\n")
    retrace.wrap("v8leg_p", "f")
    retrace.start_recording(str(ws / "traces"))
    try:
        module = importlib.import_module("v8leg_p")
        for i in range(7):
            module.f(i)
    finally:
        retrace.stop_recording()
    _write(ws, "v8new_p", "def f(x):\n    return 1 + x\n")

    serial = replay_all(str(ws / "traces"), {"v8leg_p": "v8new_p"},
                        Config(), isolate=True)
    parallel = replay_all(str(ws / "traces"), {"v8leg_p": "v8new_p"},
                          Config(), jobs=3)
    assert (serial.matched, serial.diverged_traces) == \
        (parallel.matched, parallel.diverged_traces) == (7, 0)


def test_mcp_quality_tool(ws):
    (ws / "bad.py").write_text("def f(s):\n    return eval(s)\n",
                               encoding="utf-8")
    (ws / "good.py").write_text("def f(s):\n    return s\n",
                                encoding="utf-8")
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "retrace_quality",
                    "arguments": {"files": ["bad.py"]}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "retrace_quality",
                    "arguments": {"files": ["good.py"]}}},
    ]
    payload = "".join(json.dumps(r) + "\n" for r in requests)
    proc = subprocess.run([sys.executable, "-m", "retrace.mcp_server"],
                          input=payload, capture_output=True, text=True,
                          cwd=str(ws), timeout=120)
    responses = [json.loads(line) for line in proc.stdout.splitlines()
                 if line]
    bad = responses[1]["result"]
    good = responses[2]["result"]
    assert bad["isError"] is True
    assert "eval-exec" in bad["content"][0]["text"]
    assert good["isError"] is False


class TestAttestationCoherence:
    def _setup(self, ws_dir):
        _write(ws_dir, "v8leg_a", "def f(x):\n    return x\n")
        retrace.wrap("v8leg_a", "f")
        retrace.start_recording(str(ws_dir / "traces"))
        try:
            importlib.import_module("v8leg_a").f(1)
        finally:
            retrace.stop_recording()
        from retrace.testing import verify_traces
        verify_traces("traces", {"v8leg_a": "v8leg_a"})

    def test_env_var_key_and_quality_block(self, ws, monkeypatch):
        self._setup(ws)
        monkeypatch.setenv("RETRACE_ATTEST_KEY",
                           "env-provided-signing-key-123")
        attestation = enterprise.build_attestation(
            "traces", "retrace-report.json", None,
            code_paths=["v8leg_a.py"])
        assert attestation["body"]["quality"]["errors"] == 0
        (ws / "att.json").write_text(json.dumps(attestation),
                                     encoding="utf-8")
        assert enterprise.verify_attestation(str(ws / "att.json"),
                                             None) == []

    def test_quality_block_reflects_insecure_code(self, ws, monkeypatch):
        self._setup(ws)
        monkeypatch.setenv("RETRACE_ATTEST_KEY",
                           "env-provided-signing-key-123")
        (ws / "sketchy.py").write_text("def f(s):\n    return eval(s)\n",
                                       encoding="utf-8")
        attestation = enterprise.build_attestation(
            "traces", "retrace-report.json", None,
            code_paths=["sketchy.py"])
        assert attestation["body"]["quality"]["errors"] == 1


class TestReportRobustness:
    def _fake_report(self, n_divergences, mismatch=False):
        divergences = [{"kind": "value_mismatch", "boundary": "m.f",
                        "path": "output", "input": "(%d)" % i,
                        "expected": i, "actual": i + 1, "hint": "h",
                        "trace_id": "t%d" % i}
                       for i in range(n_divergences)]
        summary = {"traces_total": n_divergences,
                   "replayed": n_divergences, "matched": 0,
                   "diverged": n_divergences, "skipped_unreplayable": 0,
                   "weak_matches": 0, "divergence_count": n_divergences,
                   "boundaries": {"m.f": {"replayed": n_divergences,
                                          "matched": 0,
                                          "diverged": n_divergences,
                                          "skipped": 0,
                                          "recorded_exceptions": 0}},
                   "recorded_python": ["3.8"], "replay_python": "3.12",
                   "python_version_mismatch": mismatch}
        return {"summary": summary, "verdict": "diverged",
                "note": "n", "divergences": divergences, "skipped": [],
                "mappings": {}}

    def test_markdown_caps_divergences(self):
        md = report_mod.render_markdown(self._fake_report(150))
        assert "Showing the first 100 divergences; 50 more" in md

    def test_python_mismatch_note(self):
        md = report_mod.render_markdown(self._fake_report(1, mismatch=True))
        assert "recorded on Python 3.8" in md and "3.12" in md
