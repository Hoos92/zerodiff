"""Retrace Enterprise: signed evidence and replay history.

Copyright (c) 2026 Retrace. This module is source-available for evaluation
and non-production use; production use requires a commercial license.
See COMMERCIAL.md. The rest of the package is MIT-licensed.
"""

import datetime
import hashlib
import hmac
import json
import os
from typing import Any, Dict, List, Optional

from .serializer import canonical_json

HISTORY_DIR = ".retrace"
HISTORY_FILE = "history.jsonl"
ATTESTATION_FILE = "retrace-attestation.json"
_LICENSE_ENV = "RETRACE_LICENSE"


def _license_notice() -> None:
    if not os.environ.get(_LICENSE_ENV):
        print("retrace: evaluation mode -- Retrace Enterprise features "
              "(attest, history) require a commercial license for "
              "production use; see COMMERCIAL.md")


# --- signed attestations -----------------------------------------------------

def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_key(key_file: Optional[str]) -> bytes:
    if key_file:
        with open(key_file, "rb") as f:
            key = f.read().strip()
    else:
        key = os.environ.get("RETRACE_ATTEST_KEY", "").strip().encode(
            "utf-8")
        if not key:
            raise ValueError("no signing key: pass --key-file or set "
                             "RETRACE_ATTEST_KEY")
    if len(key) < 16:
        raise ValueError("attestation key must be at least 16 bytes")
    return key


def _git_commit() -> Optional[str]:
    import subprocess

    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10)
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        pass
    return None


def build_attestation(trace_dir: str, report_path: str, key_file: str,
                      code_paths: Optional[List[str]] = None
                      ) -> Dict[str, Any]:
    """A tamper-evident evidence bundle: digests of every input that
    produced the verification verdict, HMAC-signed with the team key.
    ``code_paths`` optionally pins the rewrite source files that passed."""
    _license_notice()
    key = _load_key(key_file)
    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    trace_files = {}
    for name in sorted(os.listdir(trace_dir)):
        if name.endswith(".jsonl"):
            trace_files[name] = _sha256_file(os.path.join(trace_dir, name))
    if not trace_files:
        raise ValueError("no trace files found in %s" % trace_dir)

    body = {
        "attestation_version": 1,
        "created": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "key_id": hashlib.sha256(key).hexdigest()[:12],
        "traces": trace_files,
        "report_sha256": _sha256_file(report_path),
        "verdict": report["verdict"],
        "summary": report["summary"],
        "claim": "The replayed code matched {matched} of {replayed} "
                 "recorded behaviors at the time of attestation. "
                 "Equivalence is asserted over recorded behaviors "
                 "only.".format(matched=report["summary"]["matched"],
                                replayed=report["summary"]["replayed"]),
    }
    if code_paths:
        body["code"] = {path: _sha256_file(path)
                        for path in sorted(code_paths)}
        # signed evidence should speak to security too: run the quality
        # gate over the attested code and embed the outcome
        from . import __version__, quality

        findings = quality.check_files(sorted(code_paths))
        errors = quality.error_count(findings)
        body["quality"] = {
            "errors": errors,
            "warnings": len(findings) - errors,
            "ruleset": "retrace-" + __version__,
        }
    commit = _git_commit()
    if commit:
        body["git_commit"] = commit
    signature = hmac.new(key, canonical_json(body).encode("utf-8"),
                         hashlib.sha256).hexdigest()
    return {"body": body, "signature": signature, "algorithm": "hmac-sha256"}


def verify_attestation(attestation_path: str, key_file: str,
                       trace_dir: Optional[str] = None) -> List[str]:
    """Returns a list of problems (empty = attestation checks out)."""
    key = _load_key(key_file)
    with open(attestation_path, "r", encoding="utf-8") as f:
        attestation = json.load(f)
    body = attestation["body"]
    problems = []

    expected_sig = hmac.new(key, canonical_json(body).encode("utf-8"),
                            hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_sig,
                               attestation.get("signature", "")):
        problems.append("signature does not verify with this key "
                        "(attestation was altered, or wrong key)")
        return problems  # nothing below is trustworthy

    if trace_dir:
        for name, recorded_digest in body["traces"].items():
            path = os.path.join(trace_dir, name)
            if not os.path.exists(path):
                problems.append("trace file missing: %s" % name)
            elif _sha256_file(path) != recorded_digest:
                problems.append("trace file changed since attestation: %s"
                                % name)
    for path, recorded_digest in body.get("code", {}).items():
        if not os.path.exists(path):
            problems.append("attested code file missing: %s" % path)
        elif _sha256_file(path) != recorded_digest:
            problems.append("code file changed since attestation: %s"
                            % path)
    return problems


# --- replay history ----------------------------------------------------------

def append_history(report: Dict[str, Any], directory: str = ".") -> str:
    _license_notice()
    history_dir = os.path.join(directory, HISTORY_DIR)
    os.makedirs(history_dir, exist_ok=True)
    path = os.path.join(history_dir, HISTORY_FILE)
    s = report["summary"]
    entry = {
        "ts": report.get("generated_at"),
        "verdict": report["verdict"],
        "replayed": s["replayed"],
        "matched": s["matched"],
        "diverged": s["diverged"],
        "skipped": s["skipped_unreplayable"],
        "boundaries": len(s["boundaries"]),
        "git_commit": _git_commit(),
    }
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(entry, ensure_ascii=True) + "\n")
    return path


def show_history(directory: str = ".", limit: int = 20) -> int:
    path = os.path.join(directory, HISTORY_DIR, HISTORY_FILE)
    if not os.path.exists(path):
        print("retrace: no history yet (run replay with --history)")
        return 1
    with open(path, "r", encoding="utf-8") as f:
        entries = [json.loads(line) for line in f if line.strip()]
    print("%-27s %-9s %9s %9s %9s" % ("timestamp", "verdict", "replayed",
                                      "matched", "diverged"))
    for e in entries[-limit:]:
        print("%-27s %-9s %9d %9d %9d"
              % ((e.get("ts") or "?")[:26], e["verdict"], e["replayed"],
                 e["matched"], e["diverged"]))
    return 0
