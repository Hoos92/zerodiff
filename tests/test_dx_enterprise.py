"""Free-tier DX (init/demo/testing/junit) and Enterprise (attest/history)."""

import importlib
import json
import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ET

import pytest

import nodrift
from nodrift import enterprise, report as report_mod
from nodrift.scaffold import cmd_init
from nodrift.testing import BehaviorMismatch, verify_traces


@pytest.fixture()
def project(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    importlib.invalidate_caches()
    (tmp_path / "dxleg_a.py").write_text(textwrap.dedent("""
        def total(prices):
            return round(sum(prices), 2)
    """), encoding="utf-8")
    (tmp_path / "dxnew_good.py").write_text(textwrap.dedent("""
        def total(prices):
            return round(sum(prices), 2)
    """), encoding="utf-8")
    (tmp_path / "dxnew_bad.py").write_text(textwrap.dedent("""
        def total(prices):
            return sum(prices)
    """), encoding="utf-8")
    importlib.invalidate_caches()
    nodrift.wrap("dxleg_a", "total")
    nodrift.start_recording(str(tmp_path / "traces"))
    try:
        module = importlib.import_module("dxleg_a")
        module.total([1.111, 2.222])
        module.total([])
    finally:
        nodrift.stop_recording()
    yield tmp_path
    for name in list(sys.modules):
        if name.startswith(("dxleg_", "dxnew_")):
            del sys.modules[name]


class TestInit:
    def test_creates_config_and_gitignore(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert cmd_init() == 0
        config = (tmp_path / "nodrift.toml").read_text(encoding="utf-8")
        assert "[map]" in config and "redact_fields" in config
        gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
        assert "traces/" in gitignore

    def test_never_overwrites_existing_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "nodrift.toml").write_text('[map]\n"a" = "b"\n',
                                               encoding="utf-8")
        cmd_init()
        assert '"a" = "b"' in (tmp_path / "nodrift.toml").read_text(
            encoding="utf-8")


def test_demo_runs_end_to_end():
    proc = subprocess.run([sys.executable, "-m", "nodrift.cli", "demo"],
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "recorded" in proc.stdout
    assert "diverged 1" in proc.stdout or "diverged" in proc.stdout


class TestVerifyTraces:
    def test_passes_and_returns_report(self, project):
        report = verify_traces("traces", {"dxleg_a": "dxnew_good"})
        assert report["summary"]["matched"] == 2

    def test_raises_assertion_with_digest(self, project):
        with pytest.raises(BehaviorMismatch) as exc:
            verify_traces("traces", {"dxleg_a": "dxnew_bad"})
        message = str(exc.value)
        assert "diverged" in message and "dxleg_a.total" in message
        assert isinstance(exc.value, AssertionError)


def test_junit_output(project):
    with pytest.raises(BehaviorMismatch) as exc:
        verify_traces("traces", {"dxleg_a": "dxnew_bad"})
    xml_text = report_mod.render_junit(exc.value.report)
    root = ET.fromstring(xml_text)
    assert root.tag == "testsuite"
    assert root.attrib["failures"] == "1"
    case = root.find("testcase")
    assert case.attrib["name"] == "dxleg_a.total"
    assert case.find("failure") is not None


class TestAttestation:
    def _setup(self, project):
        verify_traces("traces", {"dxleg_a": "dxnew_good"})
        key = project / "team.key"
        key.write_bytes(b"super-secret-signing-key-0001")
        return str(key)

    def test_sign_and_verify(self, project):
        key = self._setup(project)
        attestation = enterprise.build_attestation(
            "traces", "nodrift-report.json", key)
        (project / "att.json").write_text(json.dumps(attestation),
                                          encoding="utf-8")
        problems = enterprise.verify_attestation(str(project / "att.json"),
                                                 key, trace_dir="traces")
        assert problems == []
        assert attestation["body"]["verdict"] == "matched"
        assert "recorded behaviors only" in attestation["body"]["claim"]

    def test_tampered_body_fails_signature(self, project):
        key = self._setup(project)
        attestation = enterprise.build_attestation(
            "traces", "nodrift-report.json", key)
        attestation["body"]["summary"]["matched"] += 1  # cook the books
        (project / "att.json").write_text(json.dumps(attestation),
                                          encoding="utf-8")
        problems = enterprise.verify_attestation(str(project / "att.json"),
                                                 key)
        assert any("signature" in p for p in problems)

    def test_tampered_trace_file_detected(self, project):
        key = self._setup(project)
        attestation = enterprise.build_attestation(
            "traces", "nodrift-report.json", key)
        (project / "att.json").write_text(json.dumps(attestation),
                                          encoding="utf-8")
        trace_file = next((project / "traces").glob("*.jsonl"))
        trace_file.write_text(trace_file.read_text(encoding="utf-8")
                              .replace("3.33", "9.99"), encoding="utf-8")
        problems = enterprise.verify_attestation(str(project / "att.json"),
                                                 key, trace_dir="traces")
        assert any("changed since attestation" in p for p in problems)

    def test_wrong_key_fails(self, project):
        key = self._setup(project)
        attestation = enterprise.build_attestation(
            "traces", "nodrift-report.json", key)
        (project / "att.json").write_text(json.dumps(attestation),
                                          encoding="utf-8")
        other = project / "other.key"
        other.write_bytes(b"a-completely-different-key!!")
        problems = enterprise.verify_attestation(str(project / "att.json"),
                                                 str(other))
        assert problems


def test_history_append_and_show(project, capsys):
    report = verify_traces("traces", {"dxleg_a": "dxnew_good"})
    enterprise.append_history(report)
    enterprise.append_history(report)
    assert enterprise.show_history() == 0
    out = capsys.readouterr().out
    assert out.count("matched") >= 1
    assert len([line for line in out.splitlines()
                if "matched " in line or line.strip().endswith(" 0")]) >= 2
