"""Recording behavior at function boundaries.

Recording is active when a trace directory is set, either programmatically
(``nodrift.start_recording(dir)``) or via the ``NODRIFT_TRACE_DIR``
environment variable (which is how ``nodrift record -- <cmd>`` activates it
in a child process). When recording is inactive, decorated functions run with
near-zero overhead.

The recorder must never break the program it observes: any failure while
serializing or writing a trace is swallowed (and counted), and the original
function's return value or exception always passes through untouched.
"""

import datetime
import functools
import importlib
import itertools
import os
import time
from typing import Any, Callable, Dict, Optional

from . import serializer, store

_ENV_VAR = "NODRIFT_TRACE_DIR"
_ENV_CONFIG = "NODRIFT_CONFIG"

_seq = itertools.count()  # global chronology across all boundaries

_active_dir = None  # type: Optional[str]
_dropped = 0  # traces lost to recorder-internal errors (never raised)
_config = None  # loaded lazily on first trace write


def _get_config():
    """Config for record-time redaction (NODRIFT_CONFIG or ./nodrift.toml).
    A broken config must not break the recorded program."""
    global _config
    if _config is None:
        from .config import Config, load_config
        try:
            _config = load_config(os.environ.get(_ENV_CONFIG))
        except Exception:
            _config = Config()
    return _config


def _redact(tree, target: str, base_path: str):
    from . import scrubbers

    redact_fields = _get_config().redact_fields(target)
    if not redact_fields:
        return tree
    return scrubbers.scrub(tree, [], [], path=base_path,
                           redact_fields=redact_fields)


def start_recording(trace_dir: str) -> None:
    global _active_dir
    _active_dir = trace_dir


def stop_recording() -> None:
    global _active_dir
    _active_dir = None


def _current_trace_dir() -> Optional[str]:
    return _active_dir or os.environ.get(_ENV_VAR) or None


def dropped_count() -> int:
    return _dropped


def _boundary_target(fn: Callable) -> str:
    module = getattr(fn, "__module__", "unknown")
    qualname = getattr(fn, "__qualname__", getattr(fn, "__name__", "unknown"))
    return "{}.{}".format(module, qualname)


def _encode_input(target: str, args: tuple, kwargs: dict) -> Dict:
    return {
        "args": [_redact(serializer.encode(a), target, "input")
                 for a in args],
        "kwargs": {k: _redact(serializer.encode(v), target, "input")
                   for k, v in kwargs.items()},
    }


def compute_mutations(encoded_before: Dict, args: tuple, kwargs: dict,
                      target: str = "") -> Dict[str, Any]:
    """Re-encode arguments after the call and return the encoded
    after-state of every argument the call modified in place."""
    after = _encode_input(target, args, kwargs)
    mutations = {}
    for i, tree in enumerate(after["args"]):
        if serializer.canonical_json(tree) != serializer.canonical_json(
                encoded_before["args"][i]):
            mutations[str(i)] = tree
    for key, tree in after["kwargs"].items():
        if serializer.canonical_json(tree) != serializer.canonical_json(
                encoded_before["kwargs"][key]):
            mutations["kw:" + key] = tree
    return mutations


def _write_trace(target: str, trace_dir: str, encoded_input: Dict,
                 output: dict, duration_ms: float,
                 mutations: Optional[Dict] = None) -> None:
    global _dropped
    try:
        if output.get("type") == "return":
            output = {"type": "return",
                      "value": _redact(output.get("value"), target,
                                       "output")}
        trace = {
            "schema": store.SCHEMA_VERSION,
            "id": store.trace_id(target, encoded_input),
            "boundary": {"kind": "function", "target": target},
            "input": encoded_input,
            "output": output,
            "meta": {
                "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "seq": next(_seq),
                "duration_ms": round(duration_ms, 3),
                "py": "{}.{}.{}".format(*__import__("sys").version_info[:3]),
                "nodrift": _version(),
            },
        }
        if mutations is not None:
            # empty dict means "captured, nothing mutated"; absent means
            # "not captured (old trace or opt-out)" -- replay only checks
            # mutations when the field is present
            trace["mutations"] = mutations
        store.append_trace(trace_dir, trace)
    except Exception:
        _dropped += 1


def _version() -> str:
    from . import __version__

    return __version__


def record(fn: Callable) -> Callable:
    """Decorator marking a function boundary for recording."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        trace_dir = _current_trace_dir()
        if trace_dir is None:
            return fn(*args, **kwargs)

        target = _boundary_target(fn)
        # encode BEFORE the call so in-place argument mutation is visible;
        # recording must never break the host, so failures degrade to
        # "trace dropped", never to an exception in the host's call
        encoded_input = None
        capture_mutations = False
        try:
            encoded_input = _encode_input(target, args, kwargs)
            capture_mutations = _get_config().record_mutations()
        except Exception:
            pass

        def finish(output, duration):
            global _dropped
            if encoded_input is None:
                _dropped += 1
                return
            mutations = None
            if capture_mutations:
                try:
                    mutations = compute_mutations(encoded_input, args,
                                                  kwargs, target)
                except Exception:
                    mutations = None
            _write_trace(target, trace_dir, encoded_input, output,
                         duration, mutations)

        start = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
        except BaseException as exc:
            duration = (time.perf_counter() - start) * 1000
            finish({"type": "exception",
                    "exception": {"type": type(exc).__name__,
                                  "message": str(exc)}}, duration)
            raise
        duration = (time.perf_counter() - start) * 1000
        try:
            encoded_value = serializer.encode(result)
        except Exception:
            encoded_value = serializer._opaque(result)
        finish({"type": "return", "value": encoded_value}, duration)
        return result

    wrapper.__nodrift_wrapped__ = fn
    return wrapper


def record_class(module_name: str, class_name: str,
                 methods: Optional[list] = None) -> int:
    """Instrument the public methods of a class (including static and
    class methods). Instance methods replay when `self` is
    reconstructible -- dataclasses reconstruct automatically; other
    types need a registered adapter. Returns the number wrapped."""
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    wrapped = 0
    for name, attr in list(vars(cls).items()):
        if name.startswith("_") or (methods is not None
                                    and name not in methods):
            continue
        if isinstance(attr, staticmethod):
            setattr(cls, name, staticmethod(record(attr.__func__)))
        elif isinstance(attr, classmethod):
            setattr(cls, name, classmethod(record(attr.__func__)))
        elif callable(attr):
            if getattr(attr, "__nodrift_wrapped__", None) is not None:
                continue
            setattr(cls, name, record(attr))
        else:
            continue
        wrapped += 1
    return wrapped


def wrap(module_name: str, function_name: str) -> Callable:
    """Instrument ``module.function`` without editing its source.

    Replaces the attribute on the module object with a recording wrapper and
    returns the wrapper. Call this from a driver script before exercising the
    legacy code. Note: code that imported the function *by value*
    (``from mod import fn``) before ``wrap()`` ran keeps the raw reference.
    """
    module = importlib.import_module(module_name)
    owner = module
    parts = function_name.split(".")  # supports "Class.method"
    for part in parts[:-1]:
        owner = getattr(owner, part)
    original = getattr(owner, parts[-1])
    if getattr(original, "__nodrift_wrapped__", None) is not None:
        return original
    wrapped = record(original)
    setattr(owner, parts[-1], wrapped)
    return wrapped
