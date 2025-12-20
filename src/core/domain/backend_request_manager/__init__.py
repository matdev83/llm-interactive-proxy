"""
Domain models for backend request manager refactoring.

This package contains typed context models used by the refactored BackendRequestManager
components to avoid ad hoc dicts across boundaries.
"""

from src.core.domain.backend_request_manager.context_models import (
    ResponseProcessingContext,
    StreamingContext,
    StructuredOutputContext,
    ToolCallRetryState,
)

# Rebuild models to resolve forward references
# This is needed when using TYPE_CHECKING with forward references
try:
    from src.core.domain.chat import ChatRequest

    ResponseProcessingContext.model_rebuild()
except ImportError:
    # ChatRequest may not be available during import time, but that's okay
    # The model will be rebuilt when ChatRequest is imported elsewhere
    pass

__all__ = [
    "ResponseProcessingContext",
    "StreamingContext",
    "StructuredOutputContext",
    "ToolCallRetryState",
]
