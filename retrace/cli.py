"""The retrace command line: record | replay | report.

Exit codes: 0 = every replayed behavior matched, 1 = divergences found,
2 = harness/usage error. This makes retrace usable directly as a CI gate or
inside an agent feedback loop.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional

from . import __version__, report as report_mod, store
from .config import load_config
from .replayer import replay_all

EXIT_MATCHED = 0
EXIT_DIVERGED = 1
EXIT_ERROR = 2


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="retrace",
        description="Behavioral equivalence harness: record real behavior, "
                    "replay it against a rewrite, report every divergence.")
    parser.add_argument("--version", action="version",
                        version="retrace " + __version__)
    sub = parser.add_subparsers(dest="command")

    p_record = sub.add_parser(
        "record", help="run a command with recording enabled")
    p_record.add_argument("-o", "--out", default="traces",
                          help="trace directory (default: traces)")
    p_record.add_argument("--include", action="append", default=[],
                          metavar="PATTERN",
                          help="auto-instrument matching modules with no "
                               "source edits (e.g. --include billing or "
                               "--include 'billing.*'; repeatable). Wraps "
                               "public module-level functions. Injects a "
                               "sitecustomize via PYTHONPATH, which shadows "
                               "any existing sitecustomize for this run.")
    p_record.add_argument("--config", default=None,
                          help="retrace.toml for record-time redaction "
                               "(default: ./retrace.toml if present)")
    p_record.add_argument("cmd", nargs=argparse.REMAINDER,
                          help="command to run, e.g.: -- python driver.py")

    p_replay = sub.add_parser(
        "replay", help="replay recorded traces against the rewrite")
    p_replay.add_argument("-t", "--traces", default="traces",
                          help="trace directory (default: traces)")
    p_replay.add_argument("--map", action="append", default=[],
                          metavar="OLD:NEW",
                          help="map old module/target prefix to new, e.g. "
                               "billing:billing_v2 (repeatable; merged with "
                               "[map] in retrace.toml)")
    p_replay.add_argument("--config", default=None,
                          help="path to retrace.toml (default: ./retrace.toml "
                               "if present)")
    p_replay.add_argument("--isolate", action="store_true",
                          help="replay each call in a worker subprocess; a "
                               "rewrite that crashes, calls os._exit, or "
                               "hangs becomes a reported divergence instead "
                               "of taking the harness down")
    p_replay.add_argument("--timeout", type=float, default=30.0,
                          help="per-call timeout in seconds with --isolate "
                               "(default: 30)")
    p_replay.add_argument("--json-out", default=report_mod.REPORT_JSON)
    p_replay.add_argument("--md-out", default=report_mod.REPORT_MD)

    p_report = sub.add_parser(
        "report", help="render an existing retrace-report.json")
    p_report.add_argument("-i", "--input", default=report_mod.REPORT_JSON)
    p_report.add_argument("--format", choices=["md", "summary"],
                          default="summary")

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return EXIT_ERROR
    try:
        if args.command == "record":
            return _cmd_record(args)
        if args.command == "replay":
            return _cmd_replay(args)
        return _cmd_report(args)
    except (FileNotFoundError, ValueError) as exc:
        print("retrace: error: {}".format(exc), file=sys.stderr)
        return EXIT_ERROR


def _cmd_record(args: argparse.Namespace) -> int:
    cmd = list(args.cmd)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("retrace: error: no command given. "
              "Usage: retrace record -o traces -- python driver.py",
              file=sys.stderr)
        return EXIT_ERROR
    trace_dir = os.path.abspath(args.out)
    env = dict(os.environ)
    env["RETRACE_TRACE_DIR"] = trace_dir
    if args.config:
        env["RETRACE_CONFIG"] = os.path.abspath(args.config)

    boot_dir = None
    if args.include:
        from .autohook import SITECUSTOMIZE
        boot_dir = tempfile.mkdtemp(prefix="retrace-boot-")
        with open(os.path.join(boot_dir, "sitecustomize.py"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(SITECUSTOMIZE)
        env["RETRACE_INCLUDE"] = ",".join(args.include)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = boot_dir + (
            os.pathsep + existing if existing else "")

    before = _count_traces(trace_dir)
    try:
        proc = subprocess.run(cmd, env=env)
    finally:
        if boot_dir is not None:
            shutil.rmtree(boot_dir, ignore_errors=True)
    after, boundaries = _count_traces(trace_dir), _count_boundaries(trace_dir)
    print("retrace: recorded {} calls across {} boundaries -> {}".format(
        after - before, boundaries, trace_dir))
    if proc.returncode != 0:
        print("retrace: note: recorded command exited with code {}".format(
            proc.returncode), file=sys.stderr)
    return EXIT_MATCHED if after > before else EXIT_ERROR


def _count_traces(trace_dir: str) -> int:
    try:
        return sum(1 for _ in store.iter_traces(trace_dir))
    except FileNotFoundError:
        return 0


def _count_boundaries(trace_dir: str) -> int:
    try:
        return len({t["boundary"]["target"]
                    for t in store.iter_traces(trace_dir)})
    except FileNotFoundError:
        return 0


def _parse_map_args(entries: List[str]) -> Dict[str, str]:
    mappings = {}
    for entry in entries:
        old, sep, new = entry.partition(":")
        if not sep or not old or not new:
            raise ValueError(
                "--map expects OLD:NEW, got {!r}".format(entry))
        mappings[old] = new
    return mappings


def _cmd_replay(args: argparse.Namespace) -> int:
    # the rewrite lives in the user's project, not next to the retrace
    # script — make the working directory importable like `python x.py` would
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
    cfg = load_config(args.config)
    mappings = cfg.mappings()
    mappings.update(_parse_map_args(args.map))

    result = replay_all(args.traces, mappings, cfg,
                        isolate=args.isolate, timeout=args.timeout)
    report = report_mod.build_report(result.to_dict(), args.traces, mappings)
    report_mod.write_reports(report, args.json_out, args.md_out)

    s = report["summary"]
    print("retrace: replayed {} of {} recorded behaviors".format(
        s["replayed"], s["traces_total"]))
    print("retrace: matched {}   diverged {}   skipped {}   weak {}".format(
        s["matched"], s["diverged"], s["skipped_unreplayable"],
        s["weak_matches"]))
    print("retrace: report -> {} , {}".format(args.json_out, args.md_out))
    if s["divergence_count"] > 0:
        _print_divergence_digest(report)
        return EXIT_DIVERGED
    return EXIT_MATCHED


def _print_divergence_digest(report: Dict, limit: int = 5) -> None:
    for d in report["divergences"][:limit]:
        print("  - [{}] {} at {}".format(d["kind"], d["boundary"], d["path"]))
    remaining = len(report["divergences"]) - limit
    if remaining > 0:
        print("  ... and {} more (see report)".format(remaining))


def _cmd_report(args: argparse.Namespace) -> int:
    with open(args.input, "r", encoding="utf-8") as f:
        report = json.load(f)
    if args.format == "md":
        print(report_mod.render_markdown(report))
    else:
        s = report["summary"]
        print("verdict: {}".format(report["verdict"]))
        print("matched {} of {} replayed behaviors "
              "({} diverged, {} skipped, {} weak)".format(
                  s["matched"], s["replayed"], s["diverged"],
                  s["skipped_unreplayable"], s["weak_matches"]))
    return EXIT_MATCHED if report["summary"]["divergence_count"] == 0 \
        else EXIT_DIVERGED


if __name__ == "__main__":
    sys.exit(main())
