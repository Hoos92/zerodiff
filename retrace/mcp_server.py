"""MCP server: ``retrace mcp`` (or ``python -m retrace.mcp_server``).

Speaks Model Context Protocol (JSON-RPC 2.0, newline-delimited, stdio) with
zero dependencies, exposing verification to any MCP-capable coding agent —
Claude Code, Codex, Copilot, Cursor. Two tools:

- retrace_replay: replay recorded traces against the rewrite, get the
  summary and every divergence with hints
- retrace_report: read an existing retrace-report.json

Register with e.g.:  claude mcp add retrace -- retrace mcp
"""

import json
import sys
from typing import Any, Dict, Optional

from . import __version__, report as report_mod
from .config import Config, load_config
from .replayer import replay_all

PROTOCOL_VERSION = "2024-11-05"
MAX_TOOL_DIVERGENCES = 40

TOOLS = [
    {
        "name": "retrace_replay",
        "description": (
            "Replay recorded behavioral traces against rewritten code and "
            "report every divergence. Returns matched/diverged counts and "
            "per-divergence hints for fixing the rewrite. Equivalence is "
            "verified over recorded behaviors only."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "traces_dir": {
                    "type": "string",
                    "description": "directory of recorded .jsonl traces"},
                "map": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "old->new module prefix mapping, e.g. "
                                   '{"billing": "billing_v2"}'},
                "config": {
                    "type": "string",
                    "description": "path to retrace.toml (optional)"},
                "isolate": {
                    "type": "boolean",
                    "description": "replay in a worker subprocess (default "
                                   "true, so edits made since the last call "
                                   "are re-imported fresh)"},
                "workdir": {
                    "type": "string",
                    "description": "directory containing the rewrite "
                                   "modules (defaults to cwd)"},
            },
            "required": ["traces_dir"],
        },
    },
    {
        "name": "retrace_report",
        "description": "Read an existing retrace-report.json and return "
                       "its summary and divergences.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "report_path": {
                    "type": "string",
                    "description": "path to retrace-report.json "
                                   "(default: ./retrace-report.json)"},
            },
        },
    },
    {
        "name": "retrace_quality",
        "description": (
            "Run the security/quality gate on source files: flags "
            "eval/exec, shell=True, SQL interpolation, hardcoded secrets, "
            "unsafe deserialization, disabled TLS verification, and "
            "complexity budget violations. Error-severity findings mean "
            "the code must not ship."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "source files to analyze"},
                "config": {
                    "type": "string",
                    "description": "path to retrace.toml for [quality] "
                                   "budgets (optional)"},
            },
            "required": ["files"],
        },
    },
]


def _tool_replay(args: Dict[str, Any]) -> Dict[str, Any]:
    import os

    workdir = args.get("workdir")
    if workdir:
        os.chdir(workdir)
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
    cfg = load_config(args.get("config"))
    mappings = cfg.mappings()
    mappings.update(args.get("map") or {})
    # isolate defaults ON: the server is long-lived, and in-process replay
    # would keep testing modules as they were when first imported
    result = replay_all(args["traces_dir"], mappings, cfg,
                        isolate=bool(args.get("isolate", True)))
    report = report_mod.build_report(result.to_dict(), args["traces_dir"],
                                     mappings)
    report_mod.write_reports(report)
    return _digest(report)


def _tool_report(args: Dict[str, Any]) -> Dict[str, Any]:
    path = args.get("report_path") or report_mod.REPORT_JSON
    with open(path, "r", encoding="utf-8") as f:
        return _digest(json.load(f))


def _tool_quality(args: Dict[str, Any]) -> Dict[str, Any]:
    from . import quality

    cfg = load_config(args.get("config"))
    findings = quality.check_files(args["files"],
                                   budgets=cfg.quality_budgets(),
                                   disabled=cfg.quality_disabled())
    errors = quality.error_count(findings)
    return {
        "errors": errors,
        "warnings": len(findings) - errors,
        "findings": [f.to_dict() for f in findings],
    }


def _digest(report: Dict[str, Any]) -> Dict[str, Any]:
    divergences = report["divergences"]
    return {
        "verdict": report["verdict"],
        "summary": report["summary"],
        "note": report["note"],
        "divergences": divergences[:MAX_TOOL_DIVERGENCES],
        "divergences_truncated": max(0, len(divergences)
                                     - MAX_TOOL_DIVERGENCES),
    }


def handle_request(request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Returns a JSON-RPC response dict, or None for notifications."""
    method = request.get("method", "")
    request_id = request.get("id")
    is_notification = "id" not in request

    if method == "initialize":
        return _result(request_id, {
            "protocolVersion": request.get("params", {}).get(
                "protocolVersion", PROTOCOL_VERSION),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "retrace", "version": __version__},
        })
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})
    if method == "tools/call":
        params = request.get("params", {})
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            if name == "retrace_replay":
                payload = _tool_replay(args)
                is_error = payload["summary"]["divergence_count"] > 0
            elif name == "retrace_report":
                payload = _tool_report(args)
                is_error = payload["summary"]["divergence_count"] > 0
            elif name == "retrace_quality":
                payload = _tool_quality(args)
                is_error = payload["errors"] > 0
            else:
                return _error(request_id, -32602, "unknown tool: %s" % name)
            return _result(request_id, {
                "content": [{"type": "text",
                             "text": json.dumps(payload, ensure_ascii=True,
                                                indent=2)}],
                "isError": is_error,
            })
        except Exception as exc:
            return _result(request_id, {
                "content": [{"type": "text",
                             "text": "retrace error: %r" % exc}],
                "isError": True,
            })
    if is_notification:
        return None  # notifications/initialized etc.
    return _error(request_id, -32601, "method not found: %s" % method)


def _result(request_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": code, "message": message}}


def main() -> None:
    # protocol integrity: nothing but JSON-RPC may reach stdout
    import os

    proto_fd = os.dup(1)
    os.dup2(2, 1)
    proto = os.fdopen(proto_fd, "w", encoding="utf-8", newline="\n")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            proto.write(json.dumps(_error(None, -32700, "parse error"))
                        + "\n")
            proto.flush()
            continue
        response = handle_request(request)
        if response is not None:
            proto.write(json.dumps(response, ensure_ascii=True) + "\n")
            proto.flush()


if __name__ == "__main__":
    main()
