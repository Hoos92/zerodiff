"""`retrace migrate` — the whole verified migration in one command.

    retrace migrate \
        --include billing.pricing \
        --driver "python run_scenarios.py" \
        --map billing.pricing:pricing_v2 \
        --agent "claude -p --permission-mode acceptEdits" \
        --attest --key-file team.key

Pipeline: (1) record the legacy code's real behavior, (2) scaffold the
rewrite module with stubs for every recorded boundary, (3) drive the agent
of your choice through the replay-fix loop until every recorded behavior
matches, (4) optionally sign a tamper-evident attestation of the result.

Retrace stays the judge throughout: the agent (any CLI you name) writes
the code; verification is deterministic and contains no model.
"""

import os
import shlex
import subprocess
import sys
from typing import Dict, List

from . import report as report_mod, store
from .config import load_config
from .loop import run_loop
from .replayer import map_target

STUB_HEADER = '''\
"""Rewrite target scaffolded by `retrace migrate`.

Implement each function below so its behavior matches the recorded
behavior of the original exactly -- including exception types, messages,
and returned value types. The replay loop will report every divergence
with the exact input that exposes it.
"""
'''


def _boundaries_from_traces(trace_dir: str,
                            mappings: Dict[str, str]) -> Dict[str, Dict]:
    """new_module -> {function_name -> [sample input previews]}"""
    from .replayer import _input_preview

    modules = {}  # type: Dict[str, Dict[str, List[str]]]
    for trace in store.load_unique_traces(trace_dir):
        target = trace["boundary"]["target"]
        new_target = map_target(target, mappings)
        module_name, _, function_name = new_target.rpartition(".")
        if not module_name:
            continue
        functions = modules.setdefault(module_name, {})
        samples = functions.setdefault(function_name, [])
        if len(samples) < 3:
            samples.append(_input_preview(trace["input"]))
    return modules


def scaffold_rewrites(trace_dir: str, mappings: Dict[str, str],
                      workdir: str) -> List[str]:
    """Create stub modules for mapped rewrite targets that don't exist yet.
    Stubs raise NotImplementedError, so the first replay hands the agent
    every recorded behavior as a divergence to implement."""
    created = []
    for module_name, functions in sorted(
            _boundaries_from_traces(trace_dir, mappings).items()):
        rel_path = module_name.replace(".", os.sep) + ".py"
        path = os.path.join(workdir, rel_path)
        if os.path.exists(path):
            continue
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
            # make intermediate directories importable packages
            package_dir = workdir
            for part in module_name.split(".")[:-1]:
                package_dir = os.path.join(package_dir, part)
                init_path = os.path.join(package_dir, "__init__.py")
                if not os.path.exists(init_path):
                    with open(init_path, "w", encoding="utf-8") as f:
                        f.write("")
        lines = [STUB_HEADER]
        for function_name, samples in sorted(functions.items()):
            lines.append("")
            lines.append("def {}(*args, **kwargs):".format(function_name))
            lines.append('    """Recorded example calls:')
            for sample in samples:
                lines.append("    {}{}".format(function_name, sample[:160]))
            lines.append('    """')
            lines.append("    raise NotImplementedError("
                         '"not yet migrated: {}")'.format(function_name))
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
        created.append(rel_path)
    return created


def cmd_migrate(args) -> int:
    workdir = os.getcwd()
    if workdir not in sys.path:
        sys.path.insert(0, workdir)

    cfg = load_config(args.config)
    mappings = cfg.mappings()
    from .cli import EXIT_DIVERGED, EXIT_ERROR, EXIT_MATCHED, _parse_map_args
    mappings.update(_parse_map_args(args.map))
    if not mappings:
        print("retrace migrate: error: no mapping given -- add --map "
              "OLD:NEW or a [map] section in retrace.toml",
              file=sys.stderr)
        return EXIT_ERROR

    # step 1: record (unless traces already exist and --skip-record)
    have_traces = os.path.isdir(args.traces) and any(
        name.endswith(".jsonl") for name in os.listdir(args.traces))
    if have_traces and args.skip_record:
        print("retrace migrate: [1/4] using existing traces in %s"
              % args.traces)
    else:
        if not args.driver:
            print("retrace migrate: error: no --driver given and no "
                  "existing traces to reuse (or pass --skip-record with "
                  "recorded traces)", file=sys.stderr)
            return EXIT_ERROR
        print("retrace migrate: [1/4] recording real behavior...")
        record_cmd = [sys.executable, "-m", "retrace.cli", "record",
                      "-o", args.traces]
        for pattern in args.include:
            record_cmd += ["--include", pattern]
        record_cmd += ["--"] + shlex.split(args.driver)
        if subprocess.run(record_cmd).returncode != 0:
            print("retrace migrate: recording failed", file=sys.stderr)
            return EXIT_ERROR

    # step 2: scaffold rewrite stubs
    created = scaffold_rewrites(args.traces, mappings, workdir)
    if created:
        print("retrace migrate: [2/4] scaffolded rewrite stubs: %s"
              % ", ".join(created))
    else:
        print("retrace migrate: [2/4] rewrite modules already exist; "
              "the loop will converge them")

    # step 3: the agent loop (always isolated; edits re-import fresh)
    print("retrace migrate: [3/4] driving the agent until every recorded "
          "behavior matches...")
    remaining = run_loop(args.traces, mappings, cfg, args.agent,
                         max_iters=args.max_iters, timeout=args.timeout,
                         workdir=workdir,
                         quality_gate=not getattr(args, "no_quality",
                                                  False))
    if remaining > 0:
        print("retrace migrate: FAILED -- %d divergences remain after %d "
              "iterations (see retrace-report.md)"
              % (remaining, args.max_iters))
        return EXIT_DIVERGED

    # step 4: attestation (optional)
    if args.attest:
        if not args.key_file:
            print("retrace migrate: error: --attest requires --key-file",
                  file=sys.stderr)
            return EXIT_ERROR
        from .enterprise import ATTESTATION_FILE, build_attestation
        import json as json_mod

        attestation = build_attestation(args.traces,
                                        report_mod.REPORT_JSON,
                                        args.key_file)
        with open(ATTESTATION_FILE, "w", encoding="utf-8",
                  newline="\n") as f:
            json_mod.dump(attestation, f, indent=2)
            f.write("\n")
        print("retrace migrate: [4/4] signed attestation -> %s"
              % ATTESTATION_FILE)
    else:
        print("retrace migrate: [4/4] done (no attestation requested; "
              "add --attest --key-file KEY for signed evidence)")

    print()
    print("retrace migrate: SUCCESS -- every recorded behavior matches.")
    print("  evidence: retrace-report.md / retrace-report.json")
    print("  keep it verified: add retrace.testing.verify_traces() to "
          "your test suite")
    return EXIT_MATCHED
