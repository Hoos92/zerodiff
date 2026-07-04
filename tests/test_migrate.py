"""`retrace migrate`: record -> scaffold -> agent loop -> attestation."""

import importlib
import json
import os
import sys
import textwrap

import pytest

from retrace import cli, enterprise

LEGACY = """
def shipping_cost(weight_kg, express=False):
    if weight_kg <= 0:
        raise ValueError("weight must be positive")
    base = 4.99 + weight_kg * 1.25
    if express:
        base = base * 1.8
    return round(base, 2)
"""

DRIVER = """
import migleg_a

for w in (0.5, 1.0, 2.5, 10.0, 30.0):
    migleg_a.shipping_cost(w)
    migleg_a.shipping_cost(w, express=True)
for bad in (0, -2):
    try:
        migleg_a.shipping_cost(bad)
    except ValueError:
        pass
print("driver done")
"""

CORRECT_REWRITE = '''
"""Migrated shipping module."""

def shipping_cost(weight_kg, express=False):
    if weight_kg <= 0:
        raise ValueError("weight must be positive")
    base = 4.99 + weight_kg * 1.25
    if express:
        base = base * 1.8
    return round(base, 2)
'''

FIX_AGENT = """
import pathlib
import sys

prompt = sys.stdin.read()
assert "shipping_cost" in prompt
pathlib.Path("mignew_a.py").write_text({rewrite!r}, encoding="utf-8")
"""

NOOP_AGENT = "import sys; sys.stdin.read()\n"


@pytest.fixture()
def mig_dir(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    importlib.invalidate_caches()
    (tmp_path / "migleg_a.py").write_text(textwrap.dedent(LEGACY),
                                          encoding="utf-8")
    (tmp_path / "mig_driver.py").write_text(textwrap.dedent(DRIVER),
                                            encoding="utf-8")
    yield tmp_path
    for name in list(sys.modules):
        if name.startswith(("migleg_", "mignew_")):
            del sys.modules[name]


def _agent_cmd(script_name):
    return '"{}" {}'.format(sys.executable, script_name)


def test_migrate_end_to_end_with_attestation(mig_dir):
    (mig_dir / "fix_agent.py").write_text(
        textwrap.dedent(FIX_AGENT).format(
            rewrite=textwrap.dedent(CORRECT_REWRITE)), encoding="utf-8")
    (mig_dir / "team.key").write_bytes(b"migration-team-signing-key-01")

    code = cli.main([
        "migrate", "--include", "migleg_a",
        "--driver", '"{}" mig_driver.py'.format(sys.executable),
        "--map", "migleg_a:mignew_a",
        "--agent", _agent_cmd("fix_agent.py"),
        "--max-iters", "3",
        "--attest", "--key-file", "team.key",
    ])
    assert code == 0

    # the agent's implementation landed and matches everything
    with open("retrace-report.json", encoding="utf-8") as f:
        report = json.load(f)
    assert report["verdict"] == "matched"
    assert report["summary"]["replayed"] == 12

    # attestation written and verifies against the traces on disk
    problems = enterprise.verify_attestation(
        enterprise.ATTESTATION_FILE, "team.key", trace_dir="traces")
    assert problems == []


def test_migrate_scaffolds_stub_from_recorded_boundaries(mig_dir):
    # a do-nothing agent leaves the stub in place: we can inspect it
    (mig_dir / "noop_agent.py").write_text(NOOP_AGENT, encoding="utf-8")

    code = cli.main([
        "migrate", "--include", "migleg_a",
        "--driver", '"{}" mig_driver.py'.format(sys.executable),
        "--map", "migleg_a:mignew_a",
        "--agent", _agent_cmd("noop_agent.py"),
        "--max-iters", "2",
    ])
    assert code == 1  # diverged: nothing was implemented

    stub = (mig_dir / "mignew_a.py").read_text(encoding="utf-8")
    assert "def shipping_cost(*args, **kwargs):" in stub
    assert "Recorded example calls:" in stub
    assert "NotImplementedError" in stub
    assert "shipping_cost(0.5)" in stub or "shipping_cost(0.5," in stub


def test_migrate_requires_mapping(mig_dir, capsys):
    code = cli.main(["migrate", "--agent", "true"])
    assert code == 2
    assert "no mapping" in capsys.readouterr().err


def test_migrate_skip_record_reuses_traces(mig_dir):
    (mig_dir / "fix_agent.py").write_text(
        textwrap.dedent(FIX_AGENT).format(
            rewrite=textwrap.dedent(CORRECT_REWRITE)), encoding="utf-8")
    # first run records; second run must reuse without a driver
    assert cli.main([
        "migrate", "--include", "migleg_a",
        "--driver", '"{}" mig_driver.py'.format(sys.executable),
        "--map", "migleg_a:mignew_a",
        "--agent", _agent_cmd("fix_agent.py"), "--max-iters", "3",
    ]) == 0
    assert cli.main([
        "migrate", "--skip-record", "--map", "migleg_a:mignew_a",
        "--agent", _agent_cmd("fix_agent.py"), "--max-iters", "2",
    ]) == 0
