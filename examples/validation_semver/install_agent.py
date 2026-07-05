"""Scripted stand-in for a coding agent: installs the prepared rewrite
modules from impl_store/ (idempotent)."""

import pathlib
import shutil
import sys

sys.stdin.read()
for source in pathlib.Path("impl_store").glob("*.py"):
    shutil.copy(str(source), source.name)
print("install_agent: rewrite installed", file=sys.stderr)
