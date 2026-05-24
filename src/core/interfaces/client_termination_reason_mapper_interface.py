"""Interface for client termination reason mapper.

This module defines the interface for mapping legacy cancellation markers and
transport signals into standardized client termination reasons.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.domain.client_termination import ClientTerminationReason


class IClientTerminationReasonMapper(ABC):
    """Interface for mapping termination markers to standardized reasons.

    This mapper normalizes legacy cancellation markers (e.g., "client_disconnect",
    "stream_cancelled") and transport signals (e.g., GeneratorExit, CancelledError)
    into standardized ClientTerminationReason enum values.
    """

    @abstractmethod
    def map_reason(self, marker: str | None) -> ClientTerminationReason:
        """Map a legacy cancellation marker to a standardized reason.

        Args:
            marker: Legacy cancellation marker (e.g., "client_disconnect",
                "stream_cancelled", "user_cancelled") or None.

        Returns:
            Standardized client termination reason.
        """
        ...

    @abstractmethod
    def map_exception(self, exception: BaseException | None) -> ClientTerminationReason:
        """Map an exception to a standardized termination reason.

        Args:
            exception: Exception that may indicate client termination
                (e.g., GeneratorExit, CancelledError) or None.

        Returns:
            Standardized client termination reason.
        """
        ...
