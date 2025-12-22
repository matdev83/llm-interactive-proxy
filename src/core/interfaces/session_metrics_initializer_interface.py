"""Interface for session metrics initialization service.

This module defines the interface for ensuring session metrics exist before
End-of-Session emission, with best-effort behavior and strict timeout enforcement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from src.core.domain.session_key import SessionKey


class ISessionMetricsInitializer(ABC):
    """Interface for ensuring session metrics exist before EoS emission.

    This service ensures session_metrics records exist early in the lifecycle
    before backend work begins, with best-effort behavior and strict timeout
    enforcement to prevent blocking cancellation/EoS handling under DB slowness.

    The service is callable from both HTTP and Codebuff flows without relying
    on request-scoped state, making it suitable for use in transport-agnostic
    termination handling.
    """

    @abstractmethod
    async def ensure_session_metrics(
        self, session_key: SessionKey, *, observed_at: datetime
    ) -> None:
        """Ensure session metrics record exists for the given session.

        This method performs a best-effort upsert operation with strict timeout
        enforcement. If persistence is unavailable or times out, the method logs
        the failure and returns without raising, allowing the caller to proceed
        with cancellation/EoS handling.

        Args:
            session_key: Transport-agnostic session identity
            observed_at: Timestamp when the session was observed (used for
                start_time and last_activity)

        Behavior:
            - Best-effort: logs errors but doesn't raise on persistence failures
            - Strict timeout: enforces internal timeout (e.g., 2.0s) to prevent
              blocking cancellation/EoS flow if database is unresponsive
            - Atomic upsert: uses repository upsert with ON CONFLICT handling
              to safely handle concurrent initialization

        Preconditions:
            - session_key.primary_id must be non-empty (enforced by SessionKey)

        Postconditions:
            - If successful: session_metrics record exists with session_id =
              session_key.primary_id
            - If timeout/failure: error logged, method returns without raising

        Invariants:
            - Never blocks cancellation/EoS handling beyond timeout duration
            - Never raises exceptions (best-effort contract)
        """
