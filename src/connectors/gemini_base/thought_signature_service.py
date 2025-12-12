"""
Thought signature service for Gemini Code Assist.

This module provides an injectable service for thought signature management,
wrapping the ThoughtSignatureManager with a clean interface for DI.
"""

import logging
from typing import Any

from src.connectors.gemini_base.thought_signature_manager import (
    ThoughtSignatureManager,
    get_global_thought_signature_manager,
)

logger = logging.getLogger(__name__)


class ThoughtSignatureService:
    """Injectable service for thought signature management.

    This service wraps the ThoughtSignatureManager to provide:
    - Dependency injection capability
    - Clean interface for testing
    - Backward compatibility with the global manager
    """

    def __init__(
        self,
        manager: ThoughtSignatureManager | None = None,
        *,
        use_global_cache: bool = True,
    ) -> None:
        """Initialize the service.

        Args:
            manager: Optional ThoughtSignatureManager to use. If not provided,
                    uses the global manager when use_global_cache is True,
                    otherwise creates a new instance.
            use_global_cache: If True and manager is None, uses the global
                             singleton manager for backward compatibility.
        """
        if manager is not None:
            self._manager = manager
        elif use_global_cache:
            self._manager = get_global_thought_signature_manager()
        else:
            self._manager = ThoughtSignatureManager()

    @property
    def cache(self) -> dict[str, str]:
        """Access the internal cache (for backward compatibility)."""
        return self._manager.cache

    def inject_signatures(
        self,
        canonical_request: Any,
        session_id: str,
        *,
        legacy_cache: dict[str, str] | None = None,
    ) -> None:
        """Inject stored thought_signatures into tool_calls that are missing them.

        Args:
            canonical_request: The canonical request with messages to process
            session_id: The session ID for cache key lookup
            legacy_cache: Optional legacy class-level cache to sync with
                         (for backward compatibility during migration)
        """
        # Sync legacy cache TO manager before injection (backward compatibility)
        if legacy_cache:
            self._manager.cache.update(legacy_cache)

        self._manager.inject_signatures(canonical_request, session_id)

        # Sync manager cache back TO legacy cache (backward compatibility)
        if legacy_cache is not None:
            legacy_cache.update(self._manager.cache)

    def store_signatures_from_tool_calls(
        self,
        tool_calls: list[dict[str, Any]],
        session_id: str | None,
        *,
        legacy_cache: dict[str, str] | None = None,
    ) -> None:
        """Store thought_signatures from streaming tool call responses.

        Args:
            tool_calls: List of tool call dictionaries with potential signatures
            session_id: The session ID for cache key construction
            legacy_cache: Optional legacy class-level cache to sync with
        """
        self._manager.store_signatures_from_tool_calls(tool_calls, session_id)

        # Sync manager cache TO legacy cache (backward compatibility)
        if legacy_cache is not None:
            legacy_cache.update(self._manager.cache)

    def log_signature_state(
        self,
        canonical_request: Any,
        session_id: str,
        effective_model: str,
    ) -> None:
        """Log presence/absence of thought signatures on assistant tool calls.

        Args:
            canonical_request: The canonical request with messages to process
            session_id: The session ID
            effective_model: The model name for logging
        """
        self._manager.log_signature_state(
            canonical_request, session_id, effective_model
        )

    def clear_session_cache(self, session_id: str) -> int:
        """Clear all cached signatures for a session.

        Used when switching backends mid-session to prevent incompatible
        thought signatures from being injected into requests to the new backend.

        Args:
            session_id: The session ID prefix to match and clear

        Returns:
            Number of entries cleared from the cache
        """
        return self._manager.clear_session_cache(session_id)


# Default instance for convenience
_default_service: ThoughtSignatureService | None = None


def get_default_thought_signature_service() -> ThoughtSignatureService:
    """Get the default thought signature service instance.

    Uses the global ThoughtSignatureManager for backward compatibility.
    """
    global _default_service
    if _default_service is None:
        _default_service = ThoughtSignatureService(use_global_cache=True)
    return _default_service


__all__ = [
    "ThoughtSignatureService",
    "get_default_thought_signature_service",
]
