"""The built-in agent: wire formats, allowlist, and the full loop —
against a local stub LLM server (no network, no real keys)."""

import importlib
import json
import sys
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import nodrift
from nodrift import cli
from nodrift.agent import AgentError, BuiltinAgent, parse_llm_spec
from nodrift.config import Config
from nodrift.loop import run_loop


class _Script:
    def __init__(self):
        self.replies = []
        self.requests = []


class _StubHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        self.server.script.requests.append(
            {"path": self.path, "headers": dict(self.headers),
             "body": body})
        reply = self.server.script.replies.pop(0)
        text, finish = reply["text"], reply.get("finish", "stop")
        if self.path.endswith("/messages"):  # anthropic wire format
            payload = {"content": [{"type": "text", "text": text}],
                       "stop_reason": "max_tokens" if finish == "length"
                       else "end_turn"}
        else:  # openai wire format
            payload = {"choices": [{"message": {"content": text},
                                    "finish_reason": finish}]}
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture()
def stub():
    server = HTTPServer(("127.0.0.1", 0), _StubHandler)
    server.script = _Script()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = "http://127.0.0.1:%d" % server.server_address[1]
    yield root, server.script
    server.shutdown()


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    for env in ("OPENAI_API_KEY", "NODRIFT_LLM_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    importlib.invalidate_caches()
    yield tmp_path
    for name in list(sys.modules):
        if name.startswith(("v9leg_", "v9new_")):
            del sys.modules[name]


def _block(name, content):
    return "<<<NODRIFT-FILE: %s>>>\n%s<<<NODRIFT-END>>>" % (name, content)


class TestSpecAndKeys:
    def test_bad_specs_rejected(self):
        for bad in ("claude", "gpt:", ":model", "mystery:m"):
            with pytest.raises(AgentError):
                parse_llm_spec(bad)

    def test_compatible_requires_base_url(self):
        with pytest.raises(AgentError):
            BuiltinAgent("openai-compatible:m")

    def test_missing_key_is_actionable(self, ws, capsys, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        (ws / "f.py").write_text("x = 1\n", encoding="utf-8")
        agent = BuiltinAgent("anthropic:some-model")
        assert agent.run("prompt", [str(ws / "f.py")], str(ws)) == 1
        assert "ANTHROPIC_API_KEY" in capsys.readouterr().out


class TestWireFormats:
    def test_openai_compatible_request_shape(self, stub, ws):
        root, script = stub
        script.replies.append({"text": _block("f.py", "x = 2\n")})
        (ws / "f.py").write_text("x = 1\n", encoding="utf-8")
        agent = BuiltinAgent("openai-compatible:stub-model",
                             base_url=root + "/v1")
        assert agent.run("fix it", [str(ws / "f.py")], str(ws)) == 0
        request = script.requests[0]
        assert request["path"] == "/v1/chat/completions"
        assert request["headers"]["Authorization"] == "Bearer not-needed"
        assert request["body"]["model"] == "stub-model"
        assert request["body"]["temperature"] == 0
        roles = [m["role"] for m in request["body"]["messages"]]
        assert roles == ["system", "user"]
        assert "fix it" in request["body"]["messages"][1]["content"]
        assert (ws / "f.py").read_text(encoding="utf-8") == "x = 2\n"

    def test_anthropic_request_shape(self, stub, monkeypatch):
        root, script = stub
        script.replies.append({"text": "OK"})
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
        agent = BuiltinAgent("anthropic:stub-model", base_url=root)
        assert agent.check() == "OK"
        request = script.requests[0]
        assert request["path"] == "/v1/messages"
        headers = {k.lower(): v for k, v in request["headers"].items()}
        assert headers["x-api-key"] == "test-key-123"
        assert headers["anthropic-version"] == "2023-06-01"
        assert request["body"]["system"].startswith("You are")
        assert request["body"]["max_tokens"] == 64 or \
            request["body"]["max_tokens"] > 0


class TestSafety:
    def test_allowlist_blocks_escapes(self, stub, ws, capsys):
        root, script = stub
        script.replies.append({"text": "\n".join([
            _block("f.py", "x = 2\n"),
            _block("../evil.py", "import os\n"),
            _block("C:/evil_abs.py", "import os\n"),
            _block("other.py", "x = 3\n"),
        ])})
        (ws / "f.py").write_text("x = 1\n", encoding="utf-8")
        (ws / "other.py").write_text("x = 9\n", encoding="utf-8")
        agent = BuiltinAgent("openai-compatible:m", base_url=root + "/v1")
        # only f.py is allowlisted
        assert agent.run("p", [str(ws / "f.py")], str(ws)) == 0
        assert (ws / "f.py").read_text(encoding="utf-8") == "x = 2\n"
        assert (ws / "other.py").read_text(encoding="utf-8") == "x = 9\n"
        assert not (ws.parent / "evil.py").exists()
        out = capsys.readouterr().out
        assert "rejected" in out

    def test_no_blocks_is_failure(self, stub, ws):
        root, script = stub
        script.replies.append({"text": "I think you should refactor."})
        (ws / "f.py").write_text("x = 1\n", encoding="utf-8")
        agent = BuiltinAgent("openai-compatible:m", base_url=root + "/v1")
        assert agent.run("p", [str(ws / "f.py")], str(ws)) == 1

    def test_truncated_reply_is_failure(self, stub, ws, capsys):
        root, script = stub
        script.replies.append({"text": _block("f.py", "x ="),
                               "finish": "length"})
        (ws / "f.py").write_text("x = 1\n", encoding="utf-8")
        agent = BuiltinAgent("openai-compatible:m", base_url=root + "/v1")
        assert agent.run("p", [str(ws / "f.py")], str(ws)) == 1
        assert "truncated" in capsys.readouterr().out


def test_llm_check_command(stub, ws):
    root, script = stub
    script.replies.append({"text": "OK"})
    assert cli.main(["llm-check", "--llm", "openai-compatible:m",
                     "--llm-base-url", root + "/v1"]) == 0
    # dead endpoint -> actionable failure
    assert cli.main(["llm-check", "--llm", "openai-compatible:m",
                     "--llm-base-url", "http://127.0.0.1:9/v1"]) == 1


def test_builtin_agent_full_loop_with_quality_gate(stub, ws):
    """iteration 1: behavioral fix that uses eval() -> quality gate blocks;
    iteration 2: clean fix -> green. Both doors share the whole gate."""
    root, script = stub
    _write = lambda n, s: ((ws / n).write_text(  # noqa: E731
        textwrap.dedent(s), encoding="utf-8"), importlib.invalidate_caches())
    _write("v9leg_a.py", "def f(x):\n    return x * 2\n")
    _write("v9new_a.py", "def f(x):\n    return x * 3\n")
    nodrift.wrap("v9leg_a", "f")
    nodrift.start_recording(str(ws / "traces"))
    try:
        importlib.import_module("v9leg_a").f(5)
    finally:
        nodrift.stop_recording()

    script.replies.append({"text": _block(
        "v9new_a.py", 'def f(x):\n    return eval("%d * 2" % x)\n')})
    script.replies.append({"text": _block(
        "v9new_a.py", "def f(x):\n    return x * 2\n")})

    runner = BuiltinAgent("openai-compatible:stub-model",
                          base_url=root + "/v1")
    remaining = run_loop(str(ws / "traces"), {"v9leg_a": "v9new_a"},
                         Config(), max_iters=4, workdir=str(ws),
                         runner=runner)
    assert remaining == 0
    assert len(script.requests) == 2
    # the first prompt carried the ORIGINAL source as read-only reference
    first_prompt = script.requests[0]["body"]["messages"][1]["content"]
    assert "Original legacy source" in first_prompt
    assert "return x * 2" in first_prompt
    # the second prompt carried the quality finding to the agent
    second_prompt = script.requests[1]["body"]["messages"][1]["content"]
    assert "eval-exec" in second_prompt
