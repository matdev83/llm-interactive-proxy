"""Shim to expose ToolCallLoopDetectionMiddleware under _service name."""

from __future__ import annotations

import warnings

from .tool_call_loop_middleware import ToolCallLoopDetectionMiddleware

warnings.warn(
    "Importing from 'src.core.services.tool_call_loop_middleware_service' is deprecated; use 'src.core.services.tool_call_loop_middleware' instead",
    DeprecationWarning,
)

__all__ = ["ToolCallLoopDetectionMiddleware"]


