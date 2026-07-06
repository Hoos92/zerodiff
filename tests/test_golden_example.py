"""Golden self-test: the examples/legacy_pricing demo, end to end.

Copies the example to a temp dir, records the legacy module's behavior, then
verifies that (a) the equivalent rewrite matches 100% with exit code 0 and
(b) the buggy rewrite is caught with exit code 1 and every seeded bug class
appears in the report.
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

EXAMPLE = os.path.join(os.path.dirname(__file__), os.pardir, "examples",
                       "legacy_pricing")


def _run(cwd, *args):
    return subprocess.run(
        [sys.executable, "-m", "nodrift.cli"] + list(args),
        cwd=cwd, capture_output=True, text=True)


@pytest.fixture(scope="module")
def demo_dir(tmp_path_factory):
    target = str(tmp_path_factory.mktemp("demo") / "legacy_pricing")
    shutil.copytree(EXAMPLE, target, ignore=shutil.ignore_patterns(
        "traces", "nodrift-report.*", "__pycache__"))
    proc = _run(target, "record", "-o", "traces", "--",
                sys.executable, "driver.py")
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "recorded" in proc.stdout
    return target


def test_equivalent_rewrite_matches_everything(demo_dir):
    proc = _run(demo_dir, "replay", "-t", "traces")
    assert proc.returncode == 0, proc.stderr + proc.stdout

    with open(os.path.join(demo_dir, "nodrift-report.json"),
              encoding="utf-8") as f:
        report = json.load(f)
    s = report["summary"]
    assert s["replayed"] == s["traces_total"] > 0
    assert s["matched"] == s["replayed"]
    assert s["divergence_count"] == 0
    assert report["verdict"] == "matched"


def test_buggy_rewrite_all_five_bugs_caught(demo_dir):
    proc = _run(demo_dir, "replay", "-t", "traces",
                "--map", "pricing:pricing_buggy")
    assert proc.returncode == 1, proc.stderr + proc.stdout

    with open(os.path.join(demo_dir, "nodrift-report.json"),
              encoding="utf-8") as f:
        report = json.load(f)
    divs = report["divergences"]
    assert report["verdict"] == "diverged"

    # BUG-1: guard silently removed -> raised vs returned
    assert any(d["kind"] == "exception_mismatch" and d["path"] == "output"
               and "silently accepts" in d["hint"] for d in divs)
    # BUG-2: bulk-discount off-by-one -> wrong subtotal for a qty:10 order
    assert any(d["kind"] == "value_mismatch" and d["path"] == "output.subtotal"
               and '"qty":10,' in d["hint"] for d in divs)
    # BUG-3: tuples became lists
    assert any(d["kind"] == "type_mismatch"
               and d["path"].startswith("output.lines[") for d in divs)
    # BUG-4: tax truncated instead of rounded
    assert any(d["kind"] == "value_mismatch" and d["path"] == "output.tax"
               for d in divs)
    # BUG-5: reworded error message
    assert any(d["kind"] == "exception_mismatch"
               and d["path"] == "output.exception.message" for d in divs)

    # honest reporting: every divergence names its input and carries a hint
    assert all(d["hint"] for d in divs)


def test_report_md_renders_honestly(demo_dir):
    proc = _run(demo_dir, "report", "--format", "md")
    assert "replayed behaviors matched" in proc.stdout
    assert "identical" not in proc.stdout.lower()
    md_path = os.path.join(demo_dir, "nodrift-report.md")
    with open(md_path, encoding="utf-8") as f:
        md = f.read()
    assert "recorded behaviors" in md
    assert "Coverage note" in md


def test_report_summary_exit_code_reflects_divergences(demo_dir):
    proc = _run(demo_dir, "report", "--format", "summary")
    assert proc.returncode == 1  # last replay in the module run was buggy
    assert "verdict: diverged" in proc.stdout
