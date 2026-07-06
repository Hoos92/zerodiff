"""v0.11.0: dataclass replay, record_class, guard, coverage, insights."""

import dataclasses
import importlib
import json
import sys
import textwrap

import pytest

import nodrift
from nodrift import cli, report as report_mod
from nodrift.config import Config
from nodrift.insights import generate
from nodrift.replayer import replay_all
from nodrift.serializer import decode, encode


@dataclasses.dataclass
class Order:
    sku: str
    qty: int


def test_dataclass_round_trips_through_decode():
    order = Order("A1", 3)
    restored = decode(encode(order))
    assert restored == order and isinstance(restored, Order)


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    importlib.invalidate_caches()
    yield tmp_path
    for name in list(sys.modules):
        if name.startswith("v11"):
            del sys.modules[name]


CLASS_MODULE = """
import dataclasses


@dataclasses.dataclass
class Cart:
    items: list

    def total(self, tax):
        return round(sum(self.items) * (1 + tax), 2)

    @staticmethod
    def fee(amount):
        return round(amount * 0.03, 2)
"""


def test_record_class_and_replay_dataclass_methods(ws):
    (ws / "v11shop.py").write_text(textwrap.dedent(CLASS_MODULE),
                                   encoding="utf-8")
    importlib.invalidate_caches()
    assert nodrift.record_class("v11shop", "Cart") == 2

    nodrift.start_recording(str(ws / "traces"))
    try:
        module = importlib.import_module("v11shop")
        cart = module.Cart([1.0, 2.5])
        cart.total(0.1)
        module.Cart.fee(100.0)
    finally:
        nodrift.stop_recording()

    result = replay_all(str(ws / "traces"), {"v11shop": "v11shop"},
                        Config())
    assert result.matched == 2, [d.to_dict() for d in result.divergences]
    assert not result.skipped  # the dataclass self was reconstructible


def test_guard_baseline_and_check(ws, capsys):
    (ws / "v11dep.py").write_text(
        "def f(x):\n    return x * 2\n", encoding="utf-8")
    (ws / "drv.py").write_text(textwrap.dedent("""
        import nodrift
        nodrift.wrap("v11dep", "f")
        import v11dep
        for i in range(4):
            v11dep.f(i)
    """), encoding="utf-8")
    importlib.invalidate_caches()

    assert cli.main(["guard", "baseline", "--",
                     sys.executable, "drv.py"]) == 0
    assert cli.main(["guard", "check"]) == 0
    out = capsys.readouterr()
    assert "PASS" in out.out
    assert "WARNING" not in out.err  # identity replay is intentional here

    # simulate a bad upgrade (different size so the .pyc cache can't
    # serve stale bytecode -- same-second, same-size rewrites are a
    # test artifact, not an upgrade scenario)
    (ws / "v11dep.py").write_text(
        "def f(x):\n    return (x * 3) + 100\n", encoding="utf-8")
    importlib.invalidate_caches()
    assert cli.main(["guard", "check", "--isolate"]) == 1
    assert "BEHAVIOR CHANGED" in capsys.readouterr().out


def test_coverage_block_in_report_and_md(ws):
    (ws / "v11cov.py").write_text(textwrap.dedent("""
        def f(x):
            if x < 0:
                raise ValueError("no")
            return x
    """), encoding="utf-8")
    importlib.invalidate_caches()
    nodrift.wrap("v11cov", "f")
    nodrift.start_recording(str(ws / "traces"))
    try:
        module = importlib.import_module("v11cov")
        module.f(1)
        module.f(2)
        try:
            module.f(-1)
        except ValueError:
            pass
    finally:
        nodrift.stop_recording()
    result = replay_all(str(ws / "traces"), {"v11cov": "v11cov"}, Config())
    report = report_mod.build_report(result.to_dict(), "traces",
                                     {"v11cov": "v11cov"})
    coverage = report["summary"]["coverage"]
    assert coverage == {"boundaries": 1, "behaviors": 3,
                        "exception_behaviors": 1,
                        "exception_share": round(1 / 3, 3)}
    assert "Coverage confidence: 1 boundaries" in \
        report_mod.render_markdown(report)


def test_insights_flags_missing_error_paths_and_json(capsys):
    summary = {"traces_total": 6, "replayed": 6, "matched": 6,
               "diverged": 0, "skipped_unreplayable": 0, "weak_matches": 0,
               "divergence_count": 0,
               "boundaries": {"m.f": {"replayed": 6, "matched": 6,
                                      "diverged": 0, "skipped": 0,
                                      "recorded_exceptions": 0}},
               "python_version_mismatch": False}
    tips = generate({"verdict": "matched", "summary": summary,
                     "divergences": [], "skipped": []}, [])
    assert any("No exception-path behaviors" in t and "m.f" in t
               for t in tips)
