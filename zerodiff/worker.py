"""Isolated replay worker: ``python -m zerodiff.worker``.

Speaks a JSON-lines protocol on its original stdout while user code's prints
are diverted to stderr, so a chatty rewrite can't corrupt the protocol.
One request per line in: {"target": ..., "input": {...}}; one reply per
line out. If the rewrite kills the process (os._exit, segfault), the parent
sees EOF and reports it as behavior.
"""

import json
import os
import sys

from . import serializer
from .replayer import resolve_callable


def _reply(proto, payload):
    proto.write(json.dumps(payload, ensure_ascii=True) + "\n")
    proto.flush()


def handle(request):
    target = request["target"]
    encoded_input = request["input"]
    fn, resolve_error = resolve_callable(target)
    if fn is None:
        return {"status": "missing", "detail": resolve_error}
    try:
        args = [serializer.decode(a) for a in encoded_input.get("args", [])]
        kwargs = {k: serializer.decode(v)
                  for k, v in encoded_input.get("kwargs", {}).items()}
    except serializer.OpaqueValueError as exc:
        return {"status": "unreplayable", "reason": str(exc)}
    from .replayer import _encode_args, compute_replay_mutations

    before = _encode_args(args, kwargs)
    try:
        value = fn(*args, **kwargs)
        outcome = {"status": "ok",
                   "output": {"type": "return",
                              "value": serializer.encode(value)}}
    except KeyboardInterrupt:
        raise
    except BaseException as exc:  # SystemExit etc. are behavior too
        outcome = {"status": "ok",
                   "output": {"type": "exception",
                              "exception": {"type": type(exc).__name__,
                                            "message": str(exc)}}}
    try:
        outcome["mutations"] = compute_replay_mutations(before, args,
                                                        kwargs)
    except Exception:
        pass
    return outcome


def main():
    # keep the protocol channel, divert user prints (fd 1 -> stderr)
    proto_fd = os.dup(1)
    os.dup2(2, 1)
    proto = os.fdopen(proto_fd, "w", encoding="utf-8", newline="\n")

    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    _reply(proto, {"status": "ready"})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            if request.get("op") == "exit":
                break
            _reply(proto, handle(request))
        except KeyboardInterrupt:
            break
        except Exception as exc:  # harness-side failure, not behavior
            _reply(proto, {"status": "error", "error": repr(exc)})


if __name__ == "__main__":
    main()
