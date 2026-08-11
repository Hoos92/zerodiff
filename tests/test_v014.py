"""v0.14.0: zero-replayed false "matched" verdict, attestation trust gaps.

Both bugs were found by an independent second audit pass and share one
root cause: a verification harness's worst failure mode is reporting a
clean pass when nothing was actually verified, or when the thing verified
was not, in fact, a pass.
"""

import importlib
import json
import os
import sys
import textwrap

import pytest

import nodrift
from nodrift import cli, enterprise
from nodrift import report as report_mod
from nodrift.config import Config, _parse_toml_subset, load_config
from nodrift.loop import PROMPT_FILE, run_agent
from nodrift.migrate import split_driver
from nodrift.replayer import replay_all
from nodrift.report import _verdict
from nodrift.scaffold import GITIGNORE_LINES
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


class TestMcpDoesNotLeakCwd:
    def test_workdir_is_restored_after_the_call(self, project, tmp_path):
        from nodrift import mcp_server

        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "traces").mkdir()
        before = os.getcwd()
        # a long-lived server must not strand itself in one call's project
        mcp_server._tool_replay({"traces_dir": "traces",
                                 "workdir": str(sub)})
        assert os.getcwd() == before

    def test_cwd_restored_even_when_the_call_raises(self, project, tmp_path):
        from nodrift import mcp_server

        before = os.getcwd()
        with pytest.raises(Exception):
            mcp_server._tool_replay({"traces_dir": "nope",
                                     "workdir": str(tmp_path)})
        assert os.getcwd() == before


class TestQualityGateCannotPassVacuously:
    def test_unlocatable_rewrite_blocks_instead_of_passing(
            self, project, tmp_path, capsys):
        """Replay resolves the rewrite by import; the gate resolves it by
        path. A rewrite that is importable but not where the mapping
        implies used to be scanned as an empty file list -- a green gate
        over code that was never read."""
        from nodrift.loop import run_loop

        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        mappings = {"v14leg_a": "v14new_good"}
        remaining = run_loop(str(project / "traces"), mappings, Config(),
                             agent_cmd="python -c \"pass\"", max_iters=1,
                             workdir=str(elsewhere))
        assert remaining >= 1  # not a clean pass
        assert "could not locate source" in capsys.readouterr().err

    def test_locatable_rewrite_still_passes_cleanly(self, project):
        from nodrift.loop import run_loop

        remaining = run_loop(str(project / "traces"),
                             {"v14leg_a": "v14new_good"}, Config(),
                             agent_cmd="python -c \"pass\"", max_iters=1,
                             workdir=str(project))
        assert remaining == 0


class TestAttestationCoversAddedTraces:
    def test_added_trace_file_is_flagged(self, project):
        verify_traces("traces", {"v14leg_a": "v14new_good"})
        key = project / "team.key"
        key.write_bytes(b"attestation-signing-key-000001")
        attestation = enterprise.build_attestation(
            "traces", "nodrift-report.json", str(key))
        (project / "att.json").write_text(json.dumps(attestation),
                                          encoding="utf-8")
        # unattested behaviors dropped in next to attested ones must not
        # read as covered by the signature
        (project / "traces" / "sneaked_in.jsonl").write_text(
            "{}\n", encoding="utf-8")
        problems = enterprise.verify_attestation(
            str(project / "att.json"), str(key), trace_dir="traces")
        assert any("added since attestation" in p for p in problems)


class TestAttestQualityUsesProjectConfig:
    def test_disabled_rule_is_honored_in_the_attested_outcome(self, project):
        (project / "v14new_good.py").write_text(
            'def f(x):\n    password = "hunter2xyz"\n    return x + 1\n',
            encoding="utf-8")
        importlib.invalidate_caches()
        verify_traces("traces", {"v14leg_a": "v14new_good"})
        key = project / "team.key"
        key.write_bytes(b"attestation-signing-key-000001")

        default = enterprise.build_attestation(
            "traces", "nodrift-report.json", str(key),
            code_paths=["v14new_good.py"])
        assert default["body"]["quality"]["errors"] >= 1

        # the same file, under a project config that disables the rule the
        # loop's own gate would have skipped too
        (project / "nodrift.toml").write_text(
            '[quality]\ndisable = ["hardcoded-secret"]\n', encoding="utf-8")
        scoped = enterprise.build_attestation(
            "traces", "nodrift-report.json", str(key),
            code_paths=["v14new_good.py"], cfg=load_config("nodrift.toml"))
        assert scoped["body"]["quality"]["errors"] == 0


class TestDriverSplitting:
    def test_windows_backslash_paths_survive(self, monkeypatch):
        monkeypatch.setattr(os, "name", "nt")
        assert split_driver(r"python scripts\run.py") == \
            ["python", r"scripts\run.py"]

    def test_quoted_executable_loses_its_quotes(self, monkeypatch):
        monkeypatch.setattr(os, "name", "nt")
        # posix=False keeps backslashes but leaves quotes attached; they
        # must come back off or the OS gets them as part of the filename
        assert split_driver(r'"C:\Program Files\py.exe" run.py') == \
            [r"C:\Program Files\py.exe", "run.py"]

    def test_plain_command_unchanged(self, monkeypatch):
        monkeypatch.setattr(os, "name", "nt")
        assert split_driver("python driver.py") == ["python", "driver.py"]


class TestFixPromptCleanup:
    def test_prompt_file_is_removed_after_the_agent_runs(self, tmp_path):
        # it embeds recorded inputs/outputs and the original source
        rc = run_agent("python -c \"import sys; sys.stdin.read()\"",
                       "the fix prompt", str(tmp_path))
        assert rc == 0
        assert not (tmp_path / PROMPT_FILE).exists()

    def test_gitignore_template_covers_it(self):
        assert PROMPT_FILE in GITIGNORE_LINES
        assert "*.key" in GITIGNORE_LINES


class TestPolish:
    def test_jobs_below_one_is_rejected(self, project, capsys):
        # 0/negative silently ran serial NON-isolated replay, which is not
        # what --jobs advertises
        assert cli.main(["replay", "-t", "traces", "--jobs", "0"]) == \
            cli.EXIT_ERROR
        assert "--jobs must be >= 1" in capsys.readouterr().err

    def test_malformed_report_gets_a_clean_error(self, tmp_path,
                                                 monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "bad.json").write_text('{"parses": "but not a report"}',
                                           encoding="utf-8")
        assert cli.main(["report", "-i", "bad.json"]) == cli.EXIT_ERROR
        assert "malformed report" in capsys.readouterr().err

    def test_idless_traces_are_not_collapsed(self, tmp_path):
        from nodrift import store

        trace_dir = tmp_path / "traces"
        trace_dir.mkdir()
        rows = []
        for i in (1, 2):
            rows.append(json.dumps({
                "schema": store.SCHEMA_VERSION,
                "boundary": {"kind": "function", "target": "m.f"},
                "input": {"args": [i], "kwargs": {}},
                "output": {"type": "return", "value": i},
                "meta": {"seq": i}}))
        (trace_dir / "m.f.jsonl").write_text("\n".join(rows) + "\n",
                                             encoding="utf-8")
        # both lack "id"; dedup on None would silently drop one behavior
        assert len(store.load_unique_traces(str(trace_dir))) == 2

    def test_junit_failure_count_matches_failing_boundaries(self, project):
        with pytest.raises(BehaviorMismatch) as exc:
            verify_traces("traces", {"v14leg_a": "v14new_bad"})
        xml_text = report_mod.render_junit(exc.value.report)
        assert 'failures="1"' in xml_text


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
