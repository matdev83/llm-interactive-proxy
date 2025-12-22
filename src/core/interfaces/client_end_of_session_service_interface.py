"""Interface for client end-of-session service.

This module defines the interface for normalizing and reporting client
termination signals, orchestrating cancellation, and triggering EoS emission.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.domain.client_termination import ClientEndOfSessionSignal
from src.core.domain.session_key import SessionKey


class IClientEndOfSessionService(ABC):
    """Interface for client termination normalization and EoS orchestration.

    This service accepts client termination reports from transports, normalizes
    them into standardized signals, initiates session cancellation, and ensures
    End-of-Session events are emitted for client-terminated sessions.
    """

    @abstractmethod
    async def report_client_termination(self, signal: ClientEndOfSessionSignal) -> None:
        """Report a client termination signal and orchestrate EoS closure.

        This method:
        - Deduplicates multiple reports for the same session
        - Cancels all registered work for the session (before blocking operations)
        - Ensures session metrics exist (defensive fallback)
        - Emits an End-of-Session event with client-termination signal type

        Args:
            signal: Normalized client termination signal with session metadata

        Behavior:
            - Idempotent: multiple calls for the same session produce a single EoS event
            - Fail-open: EoS emission proceeds even if metrics initialization fails
            - Performance: cancellation initiated before blocking persistence work
        """
        ...

    @abstractmethod
    async def report_client_termination_if_applicable(
        self, session_key: SessionKey, observed_exception: BaseException | None
    ) -> None:
        """Report client termination if the exception indicates termination.

        This method detects cancellation exceptions (CancelledError, GeneratorExit)
        and maps them to client termination signals. If the exception does not
        indicate client termination, this method does nothing.

        Args:
            session_key: The lifecycle session identifier
            observed_exception: Exception that may indicate client termination
                (e.g., CancelledError, GeneratorExit) or None

        Behavior:
            - Only reports termination if exception maps to a known termination reason
            - Uses reason mapper to normalize exception to termination reason
            - Does nothing if exception is None or doesn't indicate termination
        """
        ...
