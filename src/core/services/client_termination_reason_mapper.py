"""Client termination reason mapper implementation.

This module implements mapping of legacy cancellation markers and transport
signals into standardized client termination reasons.
"""

from __future__ import annotations

import asyncio

from src.core.domain.client_termination import ClientTerminationReason
from src.core.interfaces.client_termination_reason_mapper_interface import (
    IClientTerminationReasonMapper,
)


class ClientTerminationReasonMapper(IClientTerminationReasonMapper):
    """Maps legacy markers and exceptions to standardized termination reasons.

    This mapper normalizes various cancellation markers and transport signals
    into the standardized ClientTerminationReason enum values as defined in
    the client-end-of-session-handling specification.
    """

    def map_reason(self, marker: str | None) -> ClientTerminationReason:
        """Map a legacy cancellation marker to a standardized reason.

        Mapping rules:
        - "client_disconnect" → CLIENT_DISCONNECTED
        - "stream_cancelled", "user_cancelled" → CLIENT_CANCELLED
        - None or unknown → UNKNOWN_CLIENT_TERMINATION

        Args:
            marker: Legacy cancellation marker or None.

        Returns:
            Standardized client termination reason.
        """
        if marker == "client_disconnect":
            return ClientTerminationReason.CLIENT_DISCONNECTED
        if marker in ("stream_cancelled", "user_cancelled"):
            return ClientTerminationReason.CLIENT_CANCELLED
        return ClientTerminationReason.UNKNOWN_CLIENT_TERMINATION

    def map_exception(self, exception: BaseException | None) -> ClientTerminationReason:
        """Map an exception to a standardized termination reason.

        Mapping rules:
        - GeneratorExit → CLIENT_DISCONNECTED (stream consumer ended)
        - CancelledError → CLIENT_CANCELLED (explicit cancellation)
        - None or unknown → UNKNOWN_CLIENT_TERMINATION

        Args:
            exception: Exception that may indicate client termination or None.

        Returns:
            Standardized client termination reason.
        """
        if exception is None:
            return ClientTerminationReason.UNKNOWN_CLIENT_TERMINATION

        if isinstance(exception, GeneratorExit):
            return ClientTerminationReason.CLIENT_DISCONNECTED

        if isinstance(exception, asyncio.CancelledError):
            return ClientTerminationReason.CLIENT_CANCELLED

        return ClientTerminationReason.UNKNOWN_CLIENT_TERMINATION
