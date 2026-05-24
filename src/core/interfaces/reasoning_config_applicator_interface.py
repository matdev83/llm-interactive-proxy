"""Interface for reasoning configuration applicator.

Responsible for applying reasoning configuration from session to requests.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.domain.chat import ChatRequest


class IReasoningConfigApplicator(ABC):
    """Service interface for applying reasoning configuration to requests."""

    @abstractmethod
    def apply(self, request: ChatRequest, session: Any) -> ChatRequest:
        """Apply reasoning configuration from session to request.

        If `session.get_reasoning_mode()` returns None, request is unchanged.
        Numeric overrides respect edit-precision constraints.
        Prompt prefix/suffix is applied to user text in both string and multipart
        message content without altering non-text parts.

        Args:
            request: The chat completion request.
            session: The session containing reasoning configuration.

        Returns:
            The updated request with reasoning configuration applied.
        """
