"""zerodiff insights: the local self-improvement loop."""

from zerodiff.insights import generate
from zerodiff.quality import check_source


def _report(summary_overrides=None, divergences=None):
    summary = {"traces_total": 10, "replayed": 10, "matched": 10,
               "diverged": 0, "skipped_unreplayable": 0, "weak_matches": 0,
               "divergence_count": 0, "boundaries": {},
               "recorded_python": ["3.8"], "replay_python": "3.8",
               "python_version_mismatch": False}
    summary.update(summary_overrides or {})
    return {"verdict": "matched", "summary": summary,
            "divergences": divergences or [], "skipped": []}


def test_weak_and_skipped_suggestions():
    tips = generate(_report({"weak_matches": 4,
                             "skipped_unreplayable": 2}), [])
    joined = " ".join(tips)
    assert "register_adapter" in joined
    assert "cannot be reconstructed" in joined


def test_float_noise_suggestion():
    divs = [{"path": "output.total", "expected": 1.0 + i,
             "actual": 1.0 + i + 0.001, "kind": "value_mismatch"}
            for i in range(4)]
    tips = generate(_report({"divergence_count": 4}, divs), [])
    assert any("float_tolerance" in t for t in tips)


def test_mutation_and_message_suggestions():
    divs = [{"path": "mutation.args[0]", "expected": 1, "actual": 2},
            {"path": "output.exception.message", "expected": "a",
             "actual": "b"}]
    tips = generate(_report({"divergence_count": 2}, divs), [])
    joined = " ".join(tips)
    assert "in-place argument mutations" in joined
    assert "original wording" in joined


def test_hot_boundaries_and_streak():
    report = _report({"boundaries": {
        "m.a": {"replayed": 5, "matched": 1, "diverged": 4, "skipped": 0},
        "m.b": {"replayed": 5, "matched": 4, "diverged": 1, "skipped": 0},
    }, "diverged": 5})
    tips = generate(report, [])
    assert any("m.a (4)" in t for t in tips)

    history = [{"verdict": "matched"}] * 4
    tips = generate(_report(), history)
    assert any("attest" in t for t in tips)


def test_healthy_fallback():
    tips = generate(_report(), [])
    assert len(tips) == 1 and "healthy" in tips[0]


def test_inline_quality_suppression():
    source = ("import subprocess\n"
              "def f(c):\n"
              "    subprocess.run(c, shell=True)  "
              "# zerodiff-quality: ignore[shell-injection]\n")
    assert check_source(source, "x.py") == []
    # without the annotation the same code is flagged
    assert check_source(source.replace(
        "  # zerodiff-quality: ignore[shell-injection]", ""), "x.py")
