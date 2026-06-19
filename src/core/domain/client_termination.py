"""Client termination domain models.

This module defines domain models for client termination reasons and signals
used in session cancellation coordination.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from src.core.domain.session_key import SessionKey


class ClientTerminationReason(str, Enum):
    """Standardized client termination reasons.

    These values represent the normalized reasons for client-side session
    termination. All client termination signals must map to one of these values.
    """

    CLIENT_DISCONNECTED = "client_disconnected"
    """Client connection was dropped (e.g., network disconnect, socket close)."""

    CLIENT_CANCELLED = "client_cancelled"
    """Client explicitly cancelled the request (e.g., user clicked cancel)."""

    UNKNOWN_CLIENT_TERMINATION = "unknown_client_termination"
    """Client termination detected but reason cannot be determined."""


@dataclass(frozen=True)
class ClientEndOfSessionSignal:
    """Typed signal reported by transports for client termination.

    This signal represents a normalized client termination event that can be
    reported from any transport layer.

    Attributes:
        session_key: The lifecycle session identifier for cancellation/EoS scoping.
        observed_at: When the termination was observed.
        reason: Standardized termination reason.
        details: Optional bounded diagnostic detail (no secrets or auth data).
    """

    session_key: SessionKey
    observed_at: datetime
    reason: ClientTerminationReason
    details: str | None = None
