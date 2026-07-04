"""Retrace: behavioral equivalence harness.

Record what legacy code really does, replay it against a rewrite, and get
every divergence as an actionable report.
"""

__version__ = "0.3.0"

from .recorder import record, start_recording, stop_recording, wrap
from .serializer import register_adapter

__all__ = ["record", "wrap", "start_recording", "stop_recording",
           "register_adapter", "__version__"]
