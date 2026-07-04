"""Recording behavior at function boundaries.

Recording is active when a trace directory is set, either programmatically
(``retrace.start_recording(dir)``) or via the ``RETRACE_TRACE_DIR``
environment variable (which is how ``retrace record -- <cmd>`` activates it
in a child process). When recording is inactive, decorated functions run with
near-zero overhead.

The recorder must never break the program it observes: any failure while
serializing or writing a trace is swallowed (and counted), and the original
function's return value or exception always passes through untouched.
"""

import datetime
import functools
import importlib
import os
import time
from typing import Any, Callable, Optional

from . import serializer, store

_ENV_VAR = "RETRACE_TRACE_DIR"

_active_dir = None  # type: Optional[str]
_dropped = 0  # traces lost to recorder-internal errors (never raised)


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


def _write_trace(target: str, trace_dir: str, args: tuple, kwargs: dict,
                 output: dict, duration_ms: float) -> None:
    global _dropped
    try:
        encoded_input = {
            "args": [serializer.encode(a) for a in args],
            "kwargs": {k: serializer.encode(v) for k, v in kwargs.items()},
        }
        trace = {
            "schema": store.SCHEMA_VERSION,
            "id": store.trace_id(target, encoded_input),
            "boundary": {"kind": "function", "target": target},
            "input": encoded_input,
            "output": output,
            "meta": {
                "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "duration_ms": round(duration_ms, 3),
                "py": "{}.{}.{}".format(*__import__("sys").version_info[:3]),
                "retrace": _version(),
            },
        }
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
        start = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
        except BaseException as exc:
            duration = (time.perf_counter() - start) * 1000
            output = {
                "type": "exception",
                "exception": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
            }
            _write_trace(target, trace_dir, args, kwargs, output, duration)
            raise
        duration = (time.perf_counter() - start) * 1000
        try:
            encoded_value = serializer.encode(result)
        except Exception:
            encoded_value = serializer._opaque(result)
        output = {"type": "return", "value": encoded_value}
        _write_trace(target, trace_dir, args, kwargs, output, duration)
        return result

    wrapper.__retrace_wrapped__ = fn
    return wrapper


def wrap(module_name: str, function_name: str) -> Callable:
    """Instrument ``module.function`` without editing its source.

    Replaces the attribute on the module object with a recording wrapper and
    returns the wrapper. Call this from a driver script before exercising the
    legacy code. Note: code that imported the function *by value*
    (``from mod import fn``) before ``wrap()`` ran keeps the raw reference.
    """
    module = importlib.import_module(module_name)
    original = getattr(module, function_name)
    if getattr(original, "__retrace_wrapped__", None) is not None:
        return original
    wrapped = record(original)
    setattr(module, function_name, wrapped)
    return wrapped
