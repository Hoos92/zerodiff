"""v0.14.0: zero-replayed false "matched" verdict, attestation trust gaps.

Both bugs were found by an independent second audit pass and share one
root cause: a verification harness's worst failure mode is reporting a
clean pass when nothing was actually verified, or when the thing verified
was not, in fact, a pass.
"""

import importlib
import json
import sys
import textwrap

import pytest

import nodrift
from nodrift import cli, enterprise
from nodrift import report as report_mod
from nodrift.config import Config, _parse_toml_subset
from nodrift.replayer import replay_all
from nodrift.report import _verdict
from nodrift.testing import BehaviorMismatch, NoBehaviorsReplayed, \
    verify_traces


@pytest.fixture()
def project(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    importlib.invalidate_caches()
    (tmp_path / "v14leg_a.py").write_text(
        "def f(x):\n    return x + 1\n", encoding="utf-8")
    (tmp_path / "v14new_good.py").write_text(
        "def f(x):\n    return x + 1\n", encoding="utf-8")
    (tmp_path / "v14new_bad.py").write_text(
        "def f(x):\n    return x + 2\n", encoding="utf-8")
    importlib.invalidate_caches()
    nodrift.wrap("v14leg_a", "f")
    nodrift.start_recording(str(tmp_path / "traces"))
    try:
        importlib.import_module("v14leg_a").f(1)
    finally:
        nodrift.stop_recording()
    yield tmp_path
    for name in list(sys.modules):
        if name.startswith("v14"):
            del sys.modules[name]


class TestZeroReplayedVerdict:
    def test_verdict_is_no_data_not_matched(self):
        summary = {"replayed": 0, "traces_total": 0, "divergence_count": 0,
                   "skipped_unreplayable": 0, "weak_matches": 0}
        assert _verdict(summary) == "no_data"

    def test_verdict_still_matched_when_something_replayed(self):
        summary = {"replayed": 3, "traces_total": 3, "divergence_count": 0,
                   "skipped_unreplayable": 0, "weak_matches": 0}
        assert _verdict(summary) == "matched"

    def test_cli_replay_on_empty_dir_is_an_error_not_a_pass(
            self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "traces").mkdir()
        code = cli.main(["replay", "-t", "traces"])
        assert code == cli.EXIT_ERROR
        assert "0 behaviors replayed" in capsys.readouterr().err

    def test_cli_replay_on_nonexistent_dir_is_an_error_not_a_pass(
            self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        code = cli.main(["replay", "-t", "does-not-exist"])
        assert code == cli.EXIT_ERROR

    def test_guard_check_on_empty_dir_is_an_error_not_pass(
            self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "traces").mkdir()
        code = cli.main(["guard", "check", "-t", "traces"])
        assert code == cli.EXIT_ERROR
        out = capsys.readouterr()
        assert "PASS" not in out.out
        assert "ERROR" in out.err

    def test_verify_traces_raises_on_empty_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "traces").mkdir()
        with pytest.raises(NoBehaviorsReplayed) as exc:
            verify_traces("traces")
        assert isinstance(exc.value, AssertionError)
        assert "traces" in str(exc.value)

    def test_verify_traces_still_works_normally(self, project):
        report = verify_traces("traces", {"v14leg_a": "v14new_good"})
        assert report["summary"]["matched"] == 1
        with pytest.raises(BehaviorMismatch):
            verify_traces("traces", {"v14leg_a": "v14new_bad"})


class TestAttestationTrust:
    def _write_report(self, mapping):
        # verify_traces() raises on divergence, so a genuinely diverged
        # report needs the lower-level build+write path it wraps
        result = replay_all("traces", mapping, Config())
        report = report_mod.build_report(result.to_dict(), "traces", mapping)
        report_mod.write_reports(report)
        return "nodrift-report.json"

    def _diverged_report_path(self, project):
        return self._write_report({"v14leg_a": "v14new_bad"})

    def _matched_report_path(self, project):
        return self._write_report({"v14leg_a": "v14new_good"})

    def test_attest_refuses_a_diverged_report_by_default(self, project):
        report_path = self._diverged_report_path(project)
        key = project / "team.key"
        key.write_bytes(b"attestation-signing-key-000001")
        with pytest.raises(ValueError, match="refusing to attest"):
            enterprise.build_attestation("traces", report_path, str(key))

    def test_attest_allows_diverged_with_explicit_opt_in(self, project):
        report_path = self._diverged_report_path(project)
        key = project / "team.key"
        key.write_bytes(b"attestation-signing-key-000001")
        attestation = enterprise.build_attestation(
            "traces", report_path, str(key), allow_diverged=True)
        assert attestation["body"]["verdict"] == "diverged"

    def test_verify_attestation_flags_a_diverged_verdict(self, project):
        report_path = self._diverged_report_path(project)
        key = project / "team.key"
        key.write_bytes(b"attestation-signing-key-000001")
        attestation = enterprise.build_attestation(
            "traces", report_path, str(key), allow_diverged=True)
        (project / "att.json").write_text(json.dumps(attestation),
                                          encoding="utf-8")
        problems = enterprise.verify_attestation(
            str(project / "att.json"), str(key), trace_dir="traces")
        assert any("not a pass" in p or "diverged" in p for p in problems)

    def test_verify_attestation_clean_on_a_matched_verdict(self, project):
        report_path = self._matched_report_path(project)
        key = project / "team.key"
        key.write_bytes(b"attestation-signing-key-000001")
        attestation = enterprise.build_attestation(
            "traces", report_path, str(key))
        (project / "att.json").write_text(json.dumps(attestation),
                                          encoding="utf-8")
        problems = enterprise.verify_attestation(
            str(project / "att.json"), str(key), trace_dir="traces")
        assert problems == []

    def test_cli_attest_refuses_diverged(self, project, capsys):
        self._diverged_report_path(project)
        (project / "team.key").write_bytes(b"attestation-signing-key-01")
        code = cli.main(["attest", "-t", "traces", "--key-file", "team.key"])
        assert code == cli.EXIT_ERROR
        assert "refusing to attest" in capsys.readouterr().err

    def test_cli_attest_allow_diverged_flag(self, project):
        self._diverged_report_path(project)
        (project / "team.key").write_bytes(b"attestation-signing-key-01")
        code = cli.main(["attest", "-t", "traces", "--key-file", "team.key",
                         "--allow-diverged"])
        assert code == 0
        with open("nodrift-attestation.json", encoding="utf-8") as f:
            body = json.load(f)["body"]
        assert body["verdict"] == "diverged"


class TestConfigArrayOfTables:
    def test_array_of_tables_raises_clear_error(self):
        with pytest.raises(ValueError, match=r"\[\[array-of-tables\]\]"):
            _parse_toml_subset(
                '[[scrub.regex]]\npattern = "a"\nreplace = "b"\n', "<t>")

    def test_flat_string_array_still_works(self):
        # the actual supported way to configure [scrub] regex patterns on
        # this fallback parser -- must keep working after the fix above
        result = _parse_toml_subset(
            '[scrub]\nregex = ["foo.*", "bar"]\n', "<t>")
        assert result == {"scrub": {"regex": ["foo.*", "bar"]}}
