"""The security/quality gate: rules, budgets, and loop enforcement."""

import importlib
import sys
import textwrap

import pytest

import retrace
from retrace import quality
from retrace.config import Config, _parse_toml_subset
from retrace.loop import run_loop


def _rules(source, **kwargs):
    findings = quality.check_source(textwrap.dedent(source), "x.py",
                                    **kwargs)
    return sorted({f.rule for f in findings})


class TestSecurityRules:
    def test_eval_exec(self):
        assert _rules("def f(s):\n    return eval(s)\n") == ["eval-exec"]

    def test_shell_true_and_os_system(self):
        src = """
            import os, subprocess
            def f(cmd):
                os.system(cmd)
                subprocess.run(cmd, shell=True)
        """
        assert _rules(src) == ["shell-injection"]

    def test_unsafe_deserialization(self):
        src = """
            import pickle, yaml
            def f(blob, text):
                a = pickle.loads(blob)
                b = yaml.load(text)
                return a, b
        """
        assert "unsafe-deserialization" in _rules(src)

    def test_yaml_with_safe_loader_is_fine(self):
        src = """
            import yaml
            def f(text):
                return yaml.load(text, Loader=yaml.SafeLoader)
        """
        assert _rules(src) == []

    def test_sql_injection_fstring_and_percent(self):
        src = '''
            def f(cur, name):
                cur.execute(f"SELECT id FROM users WHERE name = {name}")
                cur.execute("DELETE FROM users WHERE id = %s" % name)
        '''
        assert _rules(src) == ["sql-injection"]

    def test_parameterized_sql_is_fine(self):
        src = '''
            def f(cur, name):
                cur.execute("SELECT id FROM users WHERE name = ?", (name,))
        '''
        assert _rules(src) == []

    def test_hardcoded_secret(self):
        assert "hardcoded-secret" in _rules(
            'password = "hunter2-super-secret"\n')
        assert "hardcoded-secret" in _rules(
            'KEY = "AKIAIOSFODNN7EXAMPLE"\n')

    def test_tls_verification_disabled(self):
        src = """
            import requests
            def f(url):
                return requests.get(url, verify=False)
        """
        assert _rules(src) == ["tls-verification-disabled"]

    def test_insecure_tempfile_and_weak_hash(self):
        src = """
            import tempfile, hashlib
            def f(data):
                p = tempfile.mktemp()
                return p, hashlib.md5(data)
        """
        rules = _rules(src)
        assert "insecure-tempfile" in rules and "weak-hash" in rules

    def test_syntax_error_is_a_blocking_finding(self):
        findings = quality.check_source("def f(:\n", "x.py")
        assert findings[0].rule == "syntax-error"
        assert findings[0].severity == "error"


class TestQualityRules:
    def test_exception_hygiene(self):
        src = """
            def f():
                try:
                    work()
                except:
                    pass
        """
        rules = _rules(src)
        assert "bare-except" in rules and "silent-except" in rules

    def test_mutable_default(self):
        assert "mutable-default" in _rules("def f(items=[]):\n    return items\n")

    def test_budgets_from_config(self):
        toml = "[quality]\nmax_function_lines = 3\n" \
               'disable = ["mutable-default"]\n'
        cfg = Config(_parse_toml_subset(toml, "t"))
        src = "def f(x=[]):\n    a = 1\n    b = 2\n    c = 3\n    return x\n"
        findings = quality.check_source(src, "x.py",
                                        budgets=cfg.quality_budgets(),
                                        disabled=cfg.quality_disabled())
        rules = {f.rule for f in findings}
        assert "function-length" in rules
        assert "mutable-default" not in rules

    def test_clean_code_has_no_findings(self):
        src = '''
            import subprocess

            def run_safely(argv):
                """Run a command without a shell."""
                return subprocess.run(argv, shell=False)
        '''
        assert _rules(src) == []

    def test_warnings_do_not_block(self):
        findings = quality.check_source(
            "def f(items=[]):\n    return items\n", "x.py")
        assert quality.error_count(findings) == 0


class TestLoopEnforcement:
    def test_insecure_rewrite_blocks_until_fixed(self, tmp_path,
                                                 monkeypatch):
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.chdir(tmp_path)
        importlib.invalidate_caches()
        (tmp_path / "qleg_a.py").write_text(
            "def calc(expr_a, expr_b):\n    return expr_a + expr_b\n",
            encoding="utf-8")
        importlib.invalidate_caches()
        retrace.wrap("qleg_a", "calc")
        retrace.start_recording(str(tmp_path / "traces"))
        try:
            importlib.import_module("qleg_a").calc(2, 3)
        finally:
            retrace.stop_recording()

        # behaviorally CORRECT but insecure rewrite (uses eval)
        (tmp_path / "qnew_a.py").write_text(
            'def calc(expr_a, expr_b):\n'
            '    return eval("%d + %d" % (expr_a, expr_b))\n',
            encoding="utf-8")
        # agent replaces it with the clean version when prompted
        (tmp_path / "fix.py").write_text(textwrap.dedent("""
            import pathlib, sys
            prompt = sys.stdin.read()
            assert "eval-exec" in prompt   # gate finding reached the agent
            assert "0 of" not in prompt.split("Divergences")[0]
            pathlib.Path("qnew_a.py").write_text(
                "def calc(expr_a, expr_b):\\n    return expr_a + expr_b\\n",
                encoding="utf-8")
        """), encoding="utf-8")

        remaining = run_loop(
            str(tmp_path / "traces"), {"qleg_a": "qnew_a"}, Config(),
            agent_cmd='"{}" fix.py'.format(sys.executable),
            max_iters=3, workdir=str(tmp_path))
        assert remaining == 0
        sys.modules.pop("qleg_a", None)

    def test_no_quality_flag_lets_it_pass(self, tmp_path, monkeypatch):
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.chdir(tmp_path)
        importlib.invalidate_caches()
        (tmp_path / "qleg_b.py").write_text(
            "def f(x):\n    return x\n", encoding="utf-8")
        importlib.invalidate_caches()
        retrace.wrap("qleg_b", "f")
        retrace.start_recording(str(tmp_path / "traces"))
        try:
            importlib.import_module("qleg_b").f(7)
        finally:
            retrace.stop_recording()
        (tmp_path / "qnew_b.py").write_text(
            'def f(x):\n    return eval("%d" % x)\n', encoding="utf-8")

        gated = run_loop(str(tmp_path / "traces"), {"qleg_b": "qnew_b"},
                         Config(), agent_cmd="true", max_iters=1,
                         workdir=str(tmp_path))
        ungated = run_loop(str(tmp_path / "traces"), {"qleg_b": "qnew_b"},
                           Config(), agent_cmd="true", max_iters=1,
                           workdir=str(tmp_path), quality_gate=False)
        assert gated == 1 and ungated == 0
        sys.modules.pop("qleg_b", None)
