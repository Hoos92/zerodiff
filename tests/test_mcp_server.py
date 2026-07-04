"""The MCP server, spoken to over real pipes with JSON-RPC."""

import importlib
import json
import subprocess
import sys
import textwrap

import pytest

import retrace


@pytest.fixture()
def mcp_dir(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    importlib.invalidate_caches()
    (tmp_path / "mcpleg_a.py").write_text(textwrap.dedent("""
        def scale(x):
            return x * 10
    """), encoding="utf-8")
    (tmp_path / "mcpnew_good.py").write_text(textwrap.dedent("""
        def scale(x):
            return 10 * x
    """), encoding="utf-8")
    (tmp_path / "mcpnew_bad.py").write_text(textwrap.dedent("""
        def scale(x):
            return x * 11
    """), encoding="utf-8")
    importlib.invalidate_caches()
    retrace.wrap("mcpleg_a", "scale")
    retrace.start_recording(str(tmp_path / "traces"))
    try:
        module = importlib.import_module("mcpleg_a")
        module.scale(1)
        module.scale(7)
    finally:
        retrace.stop_recording()
    yield tmp_path
    for name in list(sys.modules):
        if name.startswith(("mcpleg_", "mcpnew_")):
            del sys.modules[name]


def _speak(cwd, *requests):
    payload = "".join(json.dumps(r) + "\n" for r in requests)
    proc = subprocess.run(
        [sys.executable, "-m", "retrace.mcp_server"],
        input=payload, capture_output=True, text=True, cwd=str(cwd),
        timeout=120)
    return [json.loads(line) for line in proc.stdout.splitlines() if line]


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {}}}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}


def test_initialize_and_list_tools(mcp_dir):
    responses = _speak(
        mcp_dir, INIT, INITIALIZED,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert responses[0]["result"]["serverInfo"]["name"] == "retrace"
    tool_names = {t["name"] for t in responses[1]["result"]["tools"]}
    assert tool_names == {"retrace_replay", "retrace_report",
                          "retrace_quality"}


def test_replay_tool_matching_rewrite(mcp_dir):
    responses = _speak(
        mcp_dir, INIT, INITIALIZED,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "retrace_replay",
                    "arguments": {"traces_dir": "traces",
                                  "map": {"mcpleg_a": "mcpnew_good"}}}})
    result = responses[1]["result"]
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["verdict"] == "matched"
    assert payload["summary"]["matched"] == 2


def test_replay_tool_diverging_rewrite(mcp_dir):
    responses = _speak(
        mcp_dir, INIT, INITIALIZED,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "retrace_replay",
                    "arguments": {"traces_dir": "traces",
                                  "map": {"mcpleg_a": "mcpnew_bad"}}}})
    result = responses[1]["result"]
    assert result["isError"] is True
    payload = json.loads(result["content"][0]["text"])
    assert payload["verdict"] == "diverged"
    assert payload["divergences"][0]["hint"]


def test_unknown_method_and_ping(mcp_dir):
    responses = _speak(
        mcp_dir, INIT, INITIALIZED,
        {"jsonrpc": "2.0", "id": 5, "method": "ping"},
        {"jsonrpc": "2.0", "id": 6, "method": "bogus/method"})
    assert responses[1]["result"] == {}
    assert responses[2]["error"]["code"] == -32601
