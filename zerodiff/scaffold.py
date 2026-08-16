"""`zerodiff init` and `zerodiff demo` — the 60-second on-ramp."""

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap

CONFIG_TEMPLATE = """\
# zerodiff.toml -- behavioral verification config
# Docs: https://github.com/Hoos92/zerodiff

[map]
# Where recorded boundaries should be replayed. old prefix = new prefix:
# "billing.pricing" = "billing_v2.pricing"

[scrub]
# Normalize noise so it doesn't drown real divergences:
# float_tolerance = 1e-9
# builtin = ["uuid", "timestamp"]
# ignore_fields = ["*.request_id"]
# Redact secrets AT RECORD TIME (never written to disk):
# redact_fields = ["password", "*.api_token"]

[quality]
# Budgets for the security/quality gate (docs/SAFE_CODING.md):
# max_function_lines = 60
# max_complexity = 10
# max_nesting = 5
# disable = ["weak-hash"]
"""

GITIGNORE_LINES = ["traces/", "zerodiff-report.json", "zerodiff-report.md",
                   ".zerodiff/", "zerodiff-fix-prompt.md", "*.key"]

NEXT_STEPS = """\
zerodiff: initialized.

Next steps:
  1. record what your code really does (no source edits needed):
       zerodiff record --include yourmodule -o traces -- python your_driver.py
  2. add the old->new mapping to zerodiff.toml under [map]
  3. verify the rewrite:
       zerodiff replay -t traces
  4. gate it forever -- in your test suite:
       from zerodiff.testing import verify_traces
       def test_behavior(): verify_traces()

Try `zerodiff demo` for a 30-second guided example.
"""


def cmd_init(directory: str = ".") -> int:
    config_path = os.path.join(directory, "zerodiff.toml")
    if os.path.exists(config_path):
        print("zerodiff: zerodiff.toml already exists; leaving it untouched")
    else:
        with open(config_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(CONFIG_TEMPLATE)
        print("zerodiff: wrote zerodiff.toml")

    gitignore_path = os.path.join(directory, ".gitignore")
    existing = ""
    if os.path.exists(gitignore_path):
        with open(gitignore_path, "r", encoding="utf-8") as f:
            existing = f.read()
    missing = [line for line in GITIGNORE_LINES if line not in existing]
    if missing:
        with open(gitignore_path, "a", encoding="utf-8", newline="\n") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write("# zerodiff: traces can contain real runtime data\n")
            f.write("\n".join(missing) + "\n")
        print("zerodiff: updated .gitignore (%s)" % ", ".join(missing))

    print()
    print(NEXT_STEPS)
    return 0


# --- zerodiff demo -----------------------------------------------------------

DEMO_LEGACY = """\
def apply_discount(order_total, code):
    if code == "SAVE10":
        return round(order_total * 0.9, 2)
    if code in ("", None):
        return order_total
    raise ValueError("unknown discount code: %s" % code)
"""

DEMO_REWRITE_BUGGY = '''\
def apply_discount(order_total, code):
    """Modernized -- but is it the same?"""
    if not code:
        return order_total
    if code == "SAVE10":
        return round(order_total * 0.9, 2)
    # "improved" error message -- callers matching on it will break
    raise ValueError("invalid discount code: %s" % code)
'''

DEMO_DRIVER = """\
import demo_legacy

for total in (100.0, 19.99, 0.0):
    for code in ("SAVE10", "", None):
        demo_legacy.apply_discount(total, code)
for bad in ("SAVE20", "save10"):
    try:
        demo_legacy.apply_discount(50.0, bad)
    except ValueError:
        pass
print("demo driver: recorded real behavior of demo_legacy.apply_discount")
"""

DEMO_TOML = """\
[map]
"demo_legacy" = "demo_rewrite"
"""


def cmd_demo() -> int:
    print("zerodiff demo: a legacy function, a modernized rewrite, and the")
    print("question that matters: does the rewrite behave the same?")
    print()
    # a stable path, not mkdtemp: the demo deliberately leaves its files
    # behind for inspection (it prints the location below), so a fresh
    # random directory per run would pile up in temp forever. Reset it
    # each run so the demo always tells the same story instead of
    # appending to the previous run's traces.
    demo_dir = os.path.join(tempfile.gettempdir(), "zerodiff-demo")
    shutil.rmtree(demo_dir, ignore_errors=True)
    os.makedirs(demo_dir, exist_ok=True)
    files = {"demo_legacy.py": DEMO_LEGACY,
             "demo_rewrite.py": DEMO_REWRITE_BUGGY,
             "demo_driver.py": DEMO_DRIVER,
             "zerodiff.toml": DEMO_TOML}
    for name, content in files.items():
        with open(os.path.join(demo_dir, name), "w", encoding="utf-8",
                  newline="\n") as f:
            f.write(textwrap.dedent(content))

    print("step 1 -- record the legacy code (zero source edits):")
    print("  $ zerodiff record --include demo_legacy -o traces "
          "-- python demo_driver.py")
    code = _run(demo_dir, "record", "--include", "demo_legacy",
                "-o", "traces", "--", sys.executable, "demo_driver.py")
    if code != 0:
        return code
    print()
    print("step 2 -- replay against the modernized rewrite:")
    print("  $ zerodiff replay -t traces")
    _run(demo_dir, "replay", "-t", "traces")
    print()
    print("The rewrite LOOKED fine -- it 'improved' an error message, and")
    print("every caller matching on that message would have broken in")
    print("production. That's what recorded behavior catches.")
    print()
    print("demo files and full reports: %s" % demo_dir)
    print("start on your own code with: zerodiff init")
    return 0


def _run(cwd: str, *args: str) -> int:
    proc = subprocess.run([sys.executable, "-m", "zerodiff.cli"] + list(args),
                          cwd=cwd)
    return proc.returncode
