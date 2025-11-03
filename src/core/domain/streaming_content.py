"""Domain-level streaming content abstraction.

This module previously hosted a dedicated domain model that mirrored the
behaviour of the streaming content helpers in ``src.core.ports.streaming``.
Recent refactors removed the file entirely, but many parts of the codebase
still import :class:`StreamingContent` from this location.  The hybrid backend
work therefore regressed at import time when the file went missing.

To restore compatibility without duplicating logic, we expose the existing
``StreamingContent`` implementation from the ports layer.  This keeps a single
source of truth for streaming semantics (``is_empty`` heuristics, payload
normalisation, etc.) while maintaining the original import path expected by the
rest of the project and test suite.
"""

from __future__ import annotations

from src.core.ports.streaming import StreamingContent as _StreamingContent

__all__ = ["StreamingContent"]

StreamingContent = _StreamingContent
