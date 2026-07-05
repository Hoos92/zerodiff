"""Retrace: behavioral equivalence harness.

Record what legacy code really does, replay it against a rewrite, and get
every divergence as an actionable report.
"""

__version__ = "0.11.0"

from .recorder import (record, record_class, start_recording,
                       stop_recording, wrap)
from .serializer import register_adapter

__all__ = ["record", "record_class", "wrap", "start_recording",
           "stop_recording", "register_adapter", "__version__"]
