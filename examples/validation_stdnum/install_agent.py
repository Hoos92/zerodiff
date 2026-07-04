"""Scripted stand-in for a coding agent: installs the prepared rewrite
modules from impl_store/ (idempotent). A real run would use e.g.
--agent "claude -p --permission-mode acceptEdits" instead."""

import pathlib
import shutil
import sys

sys.stdin.read()  # consume the fix prompt like a real agent would
for source in pathlib.Path("impl_store").glob("*.py"):
    shutil.copy(str(source), source.name)
print("install_agent: rewrite modules installed", file=sys.stderr)
