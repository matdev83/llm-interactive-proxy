"""Backward-compatibility shim for response middleware service.

Re-exports middleware classes from `response_middleware.py` so imports that
expect the `_service` suffix continue to work.
"""

from __future__ import annotations

import warnings

from .response_middleware import (
    ContentFilterMiddleware,
    LoggingMiddleware,
    LoopDetectionMiddleware,
)

warnings.warn(
    "Importing from 'src.core.services.response_middleware_service' is deprecated; "
    "use 'src.core.services.response_middleware' instead",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["ContentFilterMiddleware", "LoggingMiddleware", "LoopDetectionMiddleware"]
