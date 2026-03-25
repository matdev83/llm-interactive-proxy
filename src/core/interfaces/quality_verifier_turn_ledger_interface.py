"""Turn accounting for Quality Verifier eligible-turn scheduling."""

from __future__ import annotations

from typing import Any, Protocol


class IQualityVerifierTurnLedger(Protocol):
    """Reset persisted and in-memory Quality Verifier eligible-turn counters."""

    def reset_quality_verifier_eligible_turn_count(
        self, session_key: str, session: Any | None
    ) -> None:
        """Set scaled eligible-turn counter to zero for ``session_key`` and session state.

        Args:
            session_key: ``quality_verifier_effective_session_id`` (or fallback session id).
            session: Client session object with ``state`` / ``update_state`` when available.
        """
        ...
