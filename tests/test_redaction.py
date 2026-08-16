"""Record-time redaction: secrets must never reach the trace files."""

import importlib
import sys
import textwrap

import pytest

import zerodiff
from zerodiff import recorder
from zerodiff.config import Config, _parse_toml_subset
from zerodiff.replayer import replay_all
from zerodiff.scrubbers import REDACTED, scrub

CONFIG_TOML = """
[scrub]
redact_fields = ["password", "*.api_token"]
"""


@pytest.fixture()
def redact_env(tmp_path, monkeypatch):
    cfg_path = tmp_path / "zerodiff.toml"
    cfg_path.write_text(CONFIG_TOML, encoding="utf-8")
    monkeypatch.setenv("ZERODIFF_CONFIG", str(cfg_path))
    monkeypatch.setattr(recorder, "_config", None)  # drop cached config
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    yield tmp_path
    monkeypatch.setattr(recorder, "_config", None)
    for name in list(sys.modules):
        if name.startswith("redmod_"):
            del sys.modules[name]


def test_scrub_redacts_by_key(redact_env):
    tree = {"user": "ada", "password": "hunter2",
            "auth": {"api_token": "tok123"}}
    out = scrub(tree, [], [], redact_fields=["password", "*.api_token"])
    assert out["password"] == REDACTED
    assert out["auth"]["api_token"] == REDACTED
    assert out["user"] == "ada"


def test_secrets_never_reach_disk_and_replay_still_matches(redact_env):
    (redact_env / "redmod_a.py").write_text(textwrap.dedent("""
        def login(creds):
            return {"user": creds["user"], "password": creds["password"],
                    "session": {"api_token": "issued-" + creds["password"]}}
    """), encoding="utf-8")
    traces = str(redact_env / "traces")

    zerodiff.wrap("redmod_a", "login")
    zerodiff.start_recording(traces)
    try:
        module = importlib.import_module("redmod_a")
        module.login({"user": "ada", "password": "hunter2-SECRET"})
    finally:
        zerodiff.stop_recording()

    # the secret appears nowhere in any trace file on disk
    trace_files = list((redact_env / "traces").glob("*.jsonl"))
    assert trace_files
    on_disk = "".join(p.read_text(encoding="utf-8") for p in trace_files)
    assert "hunter2-SECRET" not in on_disk
    assert REDACTED in on_disk

    # replay with the same config: both sides redacted, so behavior matches
    cfg = Config(_parse_toml_subset(CONFIG_TOML, "cfg"))
    result = replay_all(traces, {"redmod_a": "redmod_a"}, cfg)
    assert result.matched == 1 and not result.divergences


def test_divergences_carry_the_offending_input(redact_env):
    (redact_env / "redmod_b.py").write_text(
        "def f(x):\n    return x * 2\n", encoding="utf-8")
    (redact_env / "redmod_b2.py").write_text(
        "def f(x):\n    return x * 3\n", encoding="utf-8")
    traces = str(redact_env / "traces_b")

    zerodiff.wrap("redmod_b", "f")
    zerodiff.start_recording(traces)
    try:
        importlib.import_module("redmod_b").f(7)
    finally:
        zerodiff.stop_recording()

    result = replay_all(traces, {"redmod_b": "redmod_b2"}, Config())
    assert len(result.divergences) == 1
    d = result.divergences[0].to_dict()
    assert d["input"] == "(7)"
