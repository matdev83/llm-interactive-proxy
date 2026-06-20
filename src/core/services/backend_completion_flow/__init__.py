from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.services.backend_completion_flow.service import BackendCompletionFlow


def __getattr__(name: str) -> object:
    if name == "BackendCompletionFlow":
        from src.core.services.backend_completion_flow.service import (
            BackendCompletionFlow,
        )

        return BackendCompletionFlow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["BackendCompletionFlow"]
