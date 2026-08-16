"""The zerodiff command line: record | replay | report.

Exit codes: 0 = every replayed behavior matched, 1 = divergences found,
2 = harness/usage error. This makes zerodiff usable directly as a CI gate or
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
        prog="zerodiff",
        description="Behavioral equivalence harness: record real behavior, "
                    "replay it against a rewrite, report every divergence.")
    parser.add_argument("--version", action="version",
                        version="zerodiff " + __version__)
    sub = parser.add_subparsers(dest="command")

    p_record = sub.add_parser(
        "record", help="run a command with recording enabled")
    p_record.add_argument("-o", "--out", default="traces",
                          help="trace directory (default: traces)")
    p_record.add_argument("--include", action="append", default=[],
                          metavar="PATTERN",
                          help="auto-instrument matching modules with no "
                               "source edits (repeatable). --include "
                               "billing matches the module/package itself; "
                               "--include 'billing.*' matches its "
                               "submodules but NOT billing itself, so pass "
                               "both to cover a package and its children. "
                               "Wraps public module-level functions. Injects a "
                               "sitecustomize via PYTHONPATH, which shadows "
                               "any existing sitecustomize for this run.")
    p_record.add_argument("--config", default=None,
                          help="zerodiff.toml for record-time redaction "
                               "(default: ./zerodiff.toml if present)")
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
                               "[map] in zerodiff.toml)")
    p_replay.add_argument("--config", default=None,
                          help="path to zerodiff.toml (default: ./zerodiff.toml "
                               "if present)")
    p_replay.add_argument("--isolate", action="store_true",
                          help="replay each call in a worker subprocess; a "
                               "rewrite that crashes, calls os._exit, or "
                               "hangs becomes a reported divergence instead "
                               "of taking the harness down")
    p_replay.add_argument("--timeout", type=float, default=30.0,
                          help="per-call timeout in seconds with --isolate "
                               "(default: 30)")
    p_replay.add_argument("--in-order", action="store_true",
                          help="replay traces in recorded chronological "
                               "order (for code with module-level state)")
    p_replay.add_argument("--jobs", type=int, default=1,
                          help="replay in N parallel isolated workers "
                               "(implies --isolate; incompatible with "
                               "--in-order)")
    p_replay.add_argument("--json-out", default=report_mod.REPORT_JSON)
    p_replay.add_argument("--md-out", default=report_mod.REPORT_MD)
    p_replay.add_argument("--junit-out", default=None,
                          help="also write a JUnit XML report (one testcase "
                               "per boundary) for CI systems")
    p_replay.add_argument("--history", action="store_true",
                          help="append this run to .zerodiff/history.jsonl "
                               "(Enterprise)")

    p_report = sub.add_parser(
        "report", help="render an existing zerodiff-report.json")
    p_report.add_argument("-i", "--input", default=report_mod.REPORT_JSON)
    p_report.add_argument("--format", choices=["md", "summary"],
                          default="summary")

    p_loop = sub.add_parser(
        "loop", help="replay, feed divergences to a coding agent, repeat "
                     "until every recorded behavior matches")
    p_loop.add_argument("-t", "--traces", default="traces")
    p_loop.add_argument("--agent", default=None,
                        help="BYO agent command; gets the fix prompt on "
                             "stdin, or use a {prompt_file} placeholder. "
                             "e.g. --agent \"claude -p --permission-mode "
                             "acceptEdits\"")
    p_loop.add_argument("--llm", default=None, metavar="PROVIDER:MODEL",
                        help="use the built-in agent with your LLM: "
                             "anthropic:MODEL, openai:MODEL, or "
                             "openai-compatible:MODEL (with "
                             "--llm-base-url). Alternative to --agent.")
    p_loop.add_argument("--llm-base-url", default=None,
                        help="endpoint for openai-compatible (Ollama, "
                             "OpenRouter, vLLM, Gemini-compat)")
    p_loop.add_argument("--max-iters", type=int, default=5)
    p_loop.add_argument("--map", action="append", default=[],
                        metavar="OLD:NEW")
    p_loop.add_argument("--config", default=None)
    p_loop.add_argument("--timeout", type=float, default=30.0,
                        help="per-call replay timeout (loop always replays "
                             "in isolated workers so agent edits are "
                             "re-imported fresh)")
    p_loop.add_argument("--no-quality", action="store_true",
                        help="disable the security/quality gate on the "
                             "rewrite files (on by default)")
    p_loop.add_argument("--agent-timeout", type=float, default=1800.0,
                        help="kill the agent command after this many "
                             "seconds (default: 1800)")

    p_quality = sub.add_parser(
        "quality", help="run the security/quality gate on source files "
                        "(eval/exec, shell=True, SQL interpolation, "
                        "hardcoded secrets, complexity budgets...)")
    p_quality.add_argument("files", nargs="+")
    p_quality.add_argument("--config", default=None)

    sub.add_parser(
        "mcp", help="run the MCP server on stdio (register with: "
                    "claude mcp add zerodiff -- zerodiff mcp)")

    p_migrate = sub.add_parser(
        "migrate", help="the whole verified migration in one command: "
                        "record -> scaffold -> agent loop -> attestation")
    p_migrate.add_argument("--include", action="append", default=[],
                           metavar="PATTERN",
                           help="modules to record (zero-edit), repeatable")
    p_migrate.add_argument("--driver", default=None,
                           help="command that exercises the legacy code, "
                                "e.g. \"python run_scenarios.py\"")
    p_migrate.add_argument("--map", action="append", default=[],
                           metavar="OLD:NEW", help="old:new module mapping "
                           "(repeatable; merged with zerodiff.toml [map])")
    p_migrate.add_argument("--agent", default=None,
                           help="BYO agent CLI that writes/fixes the "
                                "rewrite; prompt via stdin or "
                                "{prompt_file}")
    p_migrate.add_argument("--llm", default=None,
                           metavar="PROVIDER:MODEL",
                           help="use the built-in agent with your LLM "
                                "(alternative to --agent)")
    p_migrate.add_argument("--llm-base-url", default=None)
    p_migrate.add_argument("-t", "--traces", default="traces")
    p_migrate.add_argument("--skip-record", action="store_true",
                           help="reuse existing traces instead of "
                                "re-recording")
    p_migrate.add_argument("--max-iters", type=int, default=8)
    p_migrate.add_argument("--timeout", type=float, default=30.0)
    p_migrate.add_argument("--config", default=None)
    p_migrate.add_argument("--attest", action="store_true",
                           help="finish with a signed attestation "
                                "(Enterprise; requires --key-file)")
    p_migrate.add_argument("--key-file", default=None)
    p_migrate.add_argument("--no-quality", action="store_true",
                           help="disable the security/quality gate on the "
                                "rewrite files (on by default)")
    p_migrate.add_argument("--agent-timeout", type=float, default=1800.0,
                           help="kill the agent command after this many "
                                "seconds (default: 1800)")

    sub.add_parser("init", help="scaffold zerodiff.toml and .gitignore "
                                "entries in the current project")
    sub.add_parser("demo", help="30-second guided demo: record a legacy "
                                "function, catch a rewrite's silent change")

    p_attest = sub.add_parser(
        "attest", help="(Enterprise) write a signed, tamper-evident "
                       "attestation of the last verification")
    p_attest.add_argument("-t", "--traces", default="traces")
    p_attest.add_argument("-r", "--report", default=report_mod.REPORT_JSON)
    p_attest.add_argument("--key-file", default=None,
                          help="file containing the team signing key "
                               "(>=16 bytes; or set ZERODIFF_ATTEST_KEY)")
    p_attest.add_argument("--code", action="append", default=[],
                          metavar="FILE",
                          help="also pin a rewrite source file's digest "
                               "into the attestation (repeatable)")
    p_attest.add_argument("-o", "--out", default=None)
    p_attest.add_argument("--allow-diverged", action="store_true",
                          help="attest even though the report's verdict "
                               "is not 'matched' (signs evidence of the "
                               "failure itself; refused by default)")

    p_vattest = sub.add_parser(
        "verify-attestation", help="(Enterprise) verify an attestation's "
                                   "signature and trace digests")
    p_vattest.add_argument("-i", "--input", default=None)
    p_vattest.add_argument("--key-file", default=None,
                           help="signing key file (or ZERODIFF_ATTEST_KEY)")
    p_vattest.add_argument("-t", "--traces", default=None,
                           help="also check trace files still match the "
                                "attested digests")

    p_history = sub.add_parser(
        "history", help="(Enterprise) show verification results over time")
    p_history.add_argument("-n", "--limit", type=int, default=20)

    p_insights = sub.add_parser(
        "insights", help="mine your reports and history for concrete "
                         "setup improvements (local; nothing leaves the "
                         "machine)")
    p_insights.add_argument("-i", "--input",
                            default=report_mod.REPORT_JSON)
    p_insights.add_argument("--json", action="store_true",
                            help="machine-readable output")

    p_guard = sub.add_parser(
        "guard", help="dependency-upgrade safety net: 'baseline' before "
                      "you upgrade, 'check' after -- proves the upgrade "
                      "changed nothing you recorded")
    guard_sub = p_guard.add_subparsers(dest="stage", required=True)
    pg_base = guard_sub.add_parser("baseline",
                                   help="record current behavior")
    pg_base.add_argument("-t", "--traces", default=".zerodiff/guard")
    pg_base.add_argument("--include", action="append", default=[],
                         metavar="PATTERN")
    pg_base.add_argument("--config", default=None)
    pg_base.add_argument("cmd", nargs=argparse.REMAINDER,
                         help="driver command: -- python x.py")
    pg_check = guard_sub.add_parser("check",
                                    help="replay after the upgrade")
    pg_check.add_argument("-t", "--traces", default=".zerodiff/guard")
    pg_check.add_argument("--config", default=None)
    pg_check.add_argument("--isolate", action="store_true")
    pg_check.add_argument("--timeout", type=float, default=30.0)

    p_llmcheck = sub.add_parser(
        "llm-check", help="validate an --llm key/model/endpoint with one "
                          "tiny round-trip before burning a real run")
    p_llmcheck.add_argument("--llm", required=True,
                            metavar="PROVIDER:MODEL")
    p_llmcheck.add_argument("--llm-base-url", default=None)
    p_llmcheck.add_argument("--config", default=None)

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return EXIT_ERROR
    try:
        if args.command == "record":
            return _cmd_record(args)
        if args.command == "replay":
            return _cmd_replay(args)
        if args.command == "loop":
            return _cmd_loop(args)
        if args.command == "mcp":
            from .mcp_server import main as mcp_main
            mcp_main()
            return EXIT_MATCHED
        if args.command == "migrate":
            from .migrate import cmd_migrate
            return cmd_migrate(args)
        if args.command == "init":
            from .scaffold import cmd_init
            return cmd_init()
        if args.command == "demo":
            from .scaffold import cmd_demo
            return cmd_demo()
        if args.command == "attest":
            return _cmd_attest(args)
        if args.command == "verify-attestation":
            return _cmd_verify_attestation(args)
        if args.command == "history":
            from .enterprise import show_history
            return show_history(limit=args.limit)
        if args.command == "quality":
            return _cmd_quality(args)
        if args.command == "llm-check":
            return _cmd_llm_check(args)
        if args.command == "insights":
            from .insights import cmd_insights
            return cmd_insights(args.input, as_json=args.json)
        if args.command == "guard":
            return _cmd_guard(args)
        return _cmd_report(args)
    except (FileNotFoundError, ValueError) as exc:
        print("zerodiff: error: {}".format(exc), file=sys.stderr)
        return EXIT_ERROR
    except KeyError as exc:
        # a report that parses as JSON but isn't a zerodiff report (or is
        # from a future schema) should say so, not dump a traceback
        print("zerodiff: error: malformed report -- missing {}. Regenerate "
              "it with `zerodiff replay`.".format(exc), file=sys.stderr)
        return EXIT_ERROR


def make_runner(args: argparse.Namespace, cfg):
    """Resolve the two doors: --agent (BYO CLI) or --llm (built-in).
    Falls back to [agent] llm in zerodiff.toml when neither flag is given."""
    from .loop import ShellAgent

    llm_spec = getattr(args, "llm", None) or (
        None if getattr(args, "agent", None) else cfg.agent_llm())
    if getattr(args, "agent", None) and getattr(args, "llm", None):
        raise ValueError("--agent and --llm are mutually exclusive; "
                         "pick one door")
    if args.agent:
        return ShellAgent(args.agent, args.agent_timeout)
    if llm_spec:
        from .agent import BuiltinAgent

        return BuiltinAgent(
            llm_spec,
            base_url=getattr(args, "llm_base_url", None)
            or cfg.agent_base_url(),
            max_tokens=cfg.agent_max_tokens(),
            timeout=args.agent_timeout,
            api_key_env=cfg.agent_api_key_env())
    raise ValueError("no agent selected: pass --agent \"<cli command>\" "
                     "or --llm provider:model (or set [agent] llm in "
                     "zerodiff.toml)")


def _cmd_loop(args: argparse.Namespace) -> int:
    from .loop import run_loop

    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
    cfg = load_config(args.config)
    mappings = cfg.mappings()
    mappings.update(_parse_map_args(args.map))
    remaining = run_loop(args.traces, mappings, cfg,
                         max_iters=args.max_iters,
                         timeout=args.timeout, workdir=cwd,
                         quality_gate=not args.no_quality,
                         agent_timeout=args.agent_timeout,
                         runner=make_runner(args, cfg))
    if remaining == 0:
        print("zerodiff loop: all recorded behaviors match")
        return EXIT_MATCHED
    print("zerodiff loop: %d divergences remain after %d iterations"
          % (remaining, args.max_iters))
    return EXIT_DIVERGED


def _cmd_record(args: argparse.Namespace) -> int:
    cmd = list(args.cmd)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("zerodiff: error: no command given. "
              "Usage: zerodiff record -o traces -- python driver.py",
              file=sys.stderr)
        return EXIT_ERROR
    trace_dir = os.path.abspath(args.out)
    env = dict(os.environ)
    env["ZERODIFF_TRACE_DIR"] = trace_dir
    if args.config:
        env["ZERODIFF_CONFIG"] = os.path.abspath(args.config)

    boot_dir = None
    if args.include:
        from .autohook import SITECUSTOMIZE
        boot_dir = tempfile.mkdtemp(prefix="zerodiff-boot-")
        with open(os.path.join(boot_dir, "sitecustomize.py"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write(SITECUSTOMIZE)
        env["ZERODIFF_INCLUDE"] = ",".join(args.include)
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
    # boundaries is the whole directory's total; when appending to existing
    # traces, say so rather than implying this run touched them all
    if before:
        print("zerodiff: recorded {} calls -> {} ({} boundaries in the "
              "directory total)".format(after - before, trace_dir,
                                        boundaries))
    else:
        print("zerodiff: recorded {} calls across {} boundaries -> {}".format(
            after - before, boundaries, trace_dir))
    if proc.returncode != 0:
        print("zerodiff: note: recorded command exited with code {}".format(
            proc.returncode), file=sys.stderr)
    if after <= before:
        print("zerodiff: error: no calls were recorded. Check that the "
              "command actually exercises the code, and that --include "
              "patterns are module names (e.g. 'billing.pricing'), or "
              "that boundaries are marked with @zerodiff.record / "
              "zerodiff.wrap().", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_MATCHED


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
    # the rewrite lives in the user's project, not next to the zerodiff
    # script — make the working directory importable like `python x.py` would
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
    cfg = load_config(args.config)
    mappings = cfg.mappings()
    mappings.update(_parse_map_args(args.map))

    if args.jobs < 1:
        # 0/negative silently fell through to serial, NON-isolated replay,
        # which is not what --jobs advertises
        raise ValueError("--jobs must be >= 1, got {}".format(args.jobs))
    if args.jobs > 1 and args.in_order:
        raise ValueError("--jobs and --in-order are incompatible: "
                         "parallel shards cannot preserve global order")
    result = replay_all(args.traces, mappings, cfg,
                        isolate=args.isolate or args.jobs > 1,
                        timeout=args.timeout, in_order=args.in_order,
                        jobs=args.jobs)
    _warn_if_unmapped(result, mappings)
    report = report_mod.build_report(result.to_dict(), args.traces, mappings)
    report_mod.write_reports(report, args.json_out, args.md_out)
    if args.junit_out:
        with open(args.junit_out, "w", encoding="utf-8", newline="\n") as f:
            f.write(report_mod.render_junit(report))
    if args.history:
        from .enterprise import append_history
        append_history(report)

    s = report["summary"]
    print("zerodiff: replayed {} of {} recorded behaviors".format(
        s["replayed"], s["traces_total"]))
    print("zerodiff: matched {}   diverged {}   skipped {}   weak {}".format(
        s["matched"], s["diverged"], s["skipped_unreplayable"],
        s["weak_matches"]))
    print("zerodiff: report -> {} , {}".format(args.json_out, args.md_out))
    if report["verdict"] == "no_data":
        print("zerodiff: error: 0 behaviors replayed -- this is not a pass. "
              "Check --traces points at a directory with recorded .jsonl "
              "traces.", file=sys.stderr)
        return EXIT_ERROR
    if s["divergence_count"] > 0:
        _print_divergence_digest(report)
        return EXIT_DIVERGED
    return EXIT_MATCHED


def _warn_if_unmapped(result, mappings: Dict[str, str]) -> None:
    """A passing replay with no effective mapping means the boundaries were
    replayed against the ORIGINAL modules -- trivially matching. That false
    confidence is worse than an error, so call it out loudly."""
    from .replayer import map_target

    boundaries = list(result.boundaries)
    if not boundaries:
        return
    if all(map_target(b, mappings) == b for b in boundaries):
        print("zerodiff: WARNING: no [map] entry applied to any recorded "
              "boundary -- you just replayed the original code against "
              "itself. Add --map OLD:NEW (or [map] in zerodiff.toml) to "
              "verify a rewrite.", file=sys.stderr)


def _print_divergence_digest(report: Dict, limit: int = 5) -> None:
    for d in report["divergences"][:limit]:
        print("  - [{}] {} at {}".format(d["kind"], d["boundary"], d["path"]))
    remaining = len(report["divergences"]) - limit
    if remaining > 0:
        print("  ... and {} more (see report)".format(remaining))


def _cmd_guard(args: argparse.Namespace) -> int:
    """The recurring product: prove an upgrade preserved recorded
    behavior. Boundaries replay against their ORIGINAL names on purpose
    -- the upgraded package now lives behind them."""
    if args.stage == "baseline":
        args.out = args.traces
        return _cmd_record(args)

    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
    cfg = load_config(args.config)
    result = replay_all(args.traces, {}, cfg, isolate=args.isolate,
                        timeout=args.timeout)
    report = report_mod.build_report(result.to_dict(), args.traces, {})
    report_mod.write_reports(report)
    s = report["summary"]
    if report["verdict"] == "no_data":
        print("zerodiff guard: ERROR -- 0 behaviors replayed, nothing was "
              "checked. Run 'zerodiff guard baseline' first, or check "
              "--traces.", file=sys.stderr)
        return EXIT_ERROR
    if s["divergence_count"] == 0:
        print("zerodiff guard: PASS -- %d of %d recorded behaviors "
              "preserved across the change" % (s["matched"],
                                               s["replayed"]))
        return EXIT_MATCHED
    print("zerodiff guard: BEHAVIOR CHANGED -- %d of %d recorded "
          "behaviors diverged (see zerodiff-report.md)"
          % (s["diverged"], s["replayed"]))
    _print_divergence_digest(report)
    return EXIT_DIVERGED


def _cmd_llm_check(args: argparse.Namespace) -> int:
    from .agent import AgentError, BuiltinAgent

    cfg = load_config(args.config)
    try:
        agent = BuiltinAgent(args.llm,
                             base_url=args.llm_base_url
                             or cfg.agent_base_url(),
                             max_tokens=64, timeout=60,
                             api_key_env=cfg.agent_api_key_env())
        reply = agent.check()
    except AgentError as exc:
        # a bad key/model/endpoint is a usage error, not "divergences
        # found" -- CI branching on exit codes must be able to tell the
        # difference between "the rewrite is wrong" and "we never ran"
        print("zerodiff llm-check: FAILED: %s" % exc)
        return EXIT_ERROR
    print("zerodiff llm-check: OK -- %s responded (%r)"
          % (args.llm, reply))
    return EXIT_MATCHED


def _cmd_quality(args: argparse.Namespace) -> int:
    from . import quality as quality_mod

    cfg = load_config(args.config)
    findings = quality_mod.check_files(args.files,
                                       budgets=cfg.quality_budgets(),
                                       disabled=cfg.quality_disabled())
    if not findings:
        print("zerodiff quality: no findings in %d file(s)"
              % len(args.files))
        return EXIT_MATCHED
    print(quality_mod.render_text(findings))
    errors = quality_mod.error_count(findings)
    print("zerodiff quality: %d blocking error(s), %d warning(s)"
          % (errors, len(findings) - errors))
    return EXIT_DIVERGED if errors else EXIT_MATCHED


def _cmd_attest(args: argparse.Namespace) -> int:
    from .enterprise import ATTESTATION_FILE, build_attestation

    attestation = build_attestation(args.traces, args.report, args.key_file,
                                    code_paths=args.code or None,
                                    allow_diverged=args.allow_diverged,
                                    cfg=load_config(getattr(args, "config",
                                                            None)))
    out = args.out or ATTESTATION_FILE
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(attestation, f, indent=2)
        f.write("\n")
    body = attestation["body"]
    print("zerodiff: attestation written -> %s" % out)
    print("zerodiff: verdict %r over %d trace files, key id %s"
          % (body["verdict"], len(body["traces"]), body["key_id"]))
    return EXIT_MATCHED


def _cmd_verify_attestation(args: argparse.Namespace) -> int:
    from .enterprise import ATTESTATION_FILE, verify_attestation

    problems = verify_attestation(args.input or ATTESTATION_FILE,
                                  args.key_file, trace_dir=args.traces)
    if not problems:
        print("zerodiff: attestation verified -- signature and digests "
              "check out")
        return EXIT_MATCHED
    for problem in problems:
        print("zerodiff: ATTESTATION PROBLEM: %s" % problem)
    return EXIT_DIVERGED


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
