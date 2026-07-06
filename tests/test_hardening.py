"""0.6.0 hardening: unmapped-replay warning, code-pinned attestations."""

import importlib
import json
import sys
import textwrap

import pytest

import nodrift
from nodrift import cli, enterprise
from nodrift.testing import verify_traces


@pytest.fixture()
def hard_dir(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    importlib.invalidate_caches()
    (tmp_path / "hardleg_a.py").write_text(
        "def f(x):\n    return x + 1\n", encoding="utf-8")
    importlib.invalidate_caches()
    nodrift.wrap("hardleg_a", "f")
    nodrift.start_recording(str(tmp_path / "traces"))
    try:
        importlib.import_module("hardleg_a").f(1)
    finally:
        nodrift.stop_recording()
    yield tmp_path
    sys.modules.pop("hardleg_a", None)


def test_replay_without_mapping_warns(hard_dir, capsys):
    code = cli.main(["replay", "-t", "traces"])
    assert code == 0  # replaying original against itself trivially matches
    err = capsys.readouterr().err
    assert "WARNING" in err and "original code against itself" in err


def test_replay_with_mapping_does_not_warn(hard_dir, capsys):
    (hard_dir / "hardnew_a.py").write_text(
        "def f(x):\n    return 1 + x\n", encoding="utf-8")
    importlib.invalidate_caches()  # finder cache may miss the new file
    code = cli.main(["replay", "-t", "traces", "--map",
                     "hardleg_a:hardnew_a"])
    assert code == 0
    assert "WARNING" not in capsys.readouterr().err


def test_attestation_pins_code_files_and_detects_tampering(hard_dir):
    verify_traces("traces", {"hardleg_a": "hardleg_a"})
    key = hard_dir / "k.key"
    key.write_bytes(b"0123456789abcdef-key")
    code_file = hard_dir / "hardleg_a.py"

    attestation = enterprise.build_attestation(
        "traces", "nodrift-report.json", str(key),
        code_paths=[str(code_file)])
    assert str(code_file) in attestation["body"]["code"]
    (hard_dir / "att.json").write_text(json.dumps(attestation),
                                       encoding="utf-8")
    assert enterprise.verify_attestation(str(hard_dir / "att.json"),
                                         str(key), trace_dir="traces") == []

    code_file.write_text("def f(x):\n    return x + 2\n", encoding="utf-8")
    problems = enterprise.verify_attestation(str(hard_dir / "att.json"),
                                             str(key), trace_dir="traces")
    assert any("code file changed" in p for p in problems)
