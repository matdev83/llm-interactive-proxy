"""Interface for URI parameter applicator.

Responsible for resolving and applying URI parameters with proper precedence.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.domain.chat import ChatRequest


class IURIParameterApplicator(ABC):
    """Service interface for applying URI parameters to requests."""

    @abstractmethod
    def apply(
        self,
        request: ChatRequest,
        uri_params: dict[str, Any],
        backend_type: str,
        session: Any | None = None,
    ) -> ChatRequest:
        """Apply URI parameters to request with precedence resolution.

        Sources and precedence (highest to lowest):
        1. Session overrides (from commands)
        2. URI parameters
        3. Request/extra_body fields (headers)
        4. Backend/app config

        Type coercion rules:
        - temperature, top_p -> float
        - top_k -> int (rejects non-integer floats)
        - reasoning_effort -> str

        Edit-precision mode promotes one-shot request fields into session-level precedence.

        Early-returns if uri_params is empty.

        Args:
            request: The chat completion request.
            uri_params: URI parameters to apply.
            backend_type: The backend type for context.
            session: Optional session for override resolution.

        Returns:
            The updated request with parameters applied.
        """
