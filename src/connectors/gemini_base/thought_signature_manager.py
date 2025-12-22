"""
Thought signature management for Gemini Code Assist.

This module handles server-side storage and injection of thought_signatures
for clients (like Droid) that don't preserve extra_content.
"""

import logging
import time
from collections import OrderedDict
from typing import Any

from src.core.app.constants.logging_constants import TRACE_LEVEL

logger = logging.getLogger(__name__)


class ThoughtSignatureManager:
    """Manages thought signatures for tool calls.

    Droid and similar clients don't preserve extra_content, so we store
    mapping of tool_call_id -> thought_signature server-side and
    inject it when processing subsequent requests.

    Key format: "session_id:tool_call_id" -> thought_signature
    """

    def __init__(self, max_cache_size: int = 10000, ttl_seconds: int = 3600) -> None:
        self._max_cache_size = max_cache_size
        self._ttl_seconds = ttl_seconds

        # OrderedDict for LRU eviction with timestamps
        self._cache: OrderedDict[str, tuple[str, float]] = OrderedDict()
        # Secondary index by tool_call_id to survive session-id changes
        self._by_tool_call: dict[str, str] = {}

    @property
    def cache(self) -> dict[str, str]:
        """Access to cache for backward compatibility."""
        # Convert from (sig, timestamp) tuples back to just signatures
        return {key: value for key, (value, _) in self._cache.items()}

    @cache.setter
    def cache(self, value: dict[str, str]) -> None:
        """Set cache for backward compatibility (stores with current timestamp)."""
        # Convert from just signatures to (sig, timestamp) tuples
        current_time = time.time()
        self._cache = OrderedDict(
            (key, (sig, current_time)) for key, sig in value.items()
        )

    def update(self, updates: dict[str, str]) -> None:
        """Update cache with new values (for backward compatibility)."""
        current_time = time.time()
        for key, sig in updates.items():
            self._cache[key] = (sig, current_time)
            self._cache.move_to_end(key)

    def inject_signatures(self, canonical_request: Any, session_id: str) -> None:
        """Inject stored thought_signatures into tool_calls that are missing them.

        Args:
            canonical_request: The canonical request with messages to process
            session_id: The session ID for cache key lookup
        """
        if not hasattr(canonical_request, "messages"):
            return

        for message in canonical_request.messages:
            if getattr(message, "role", None) != "assistant":
                continue
            tool_calls = getattr(message, "tool_calls", None)
            if not tool_calls:
                continue

            for tc in tool_calls:
                self._inject_signature_for_tool_call(tc, session_id)

    def _inject_signature_for_tool_call(self, tc: Any, session_id: str) -> None:
        """Inject signature for a single tool call if missing."""
        # Get tool call ID
        tc_id = None
        if isinstance(tc, dict):
            tc_id = tc.get("id")
        elif hasattr(tc, "id"):
            tc_id = tc.id

        if not tc_id:
            return

        # Check if already has thought_signature
        extra_content = None
        if isinstance(tc, dict):
            extra_content = tc.get("extra_content")
        elif hasattr(tc, "extra_content"):
            extra_content = tc.extra_content

        if extra_content:
            google_extra = (
                extra_content.get("google", {})
                if isinstance(extra_content, dict)
                else {}
            )
            if google_extra.get("thought_signature"):
                return  # Already has signature

        # Look up in cache with TTL check
        current_time = time.time()
        cache_key = f"{session_id}:{tc_id}"

        cache_entry = self._cache.get(cache_key)
        sig: str | None = None

        if cache_entry:
            cached_sig, timestamp = cache_entry
            if current_time - timestamp > self._ttl_seconds:
                # Expired, remove it
                del self._cache[cache_key]
                self._by_tool_call.pop(tc_id, None)
                sig = None
            else:
                sig = cached_sig

        if not sig:
            # Try anonymous cache if session_id was missing at store time
            anon_entry = self._cache.get(f"anon:{tc_id}")
            if anon_entry:
                anon_sig, anon_timestamp = anon_entry
                if current_time - anon_timestamp > self._ttl_seconds:
                    del self._cache[f"anon:{tc_id}"]
                    self._by_tool_call.pop(tc_id, None)
                    sig = None
                else:
                    sig = anon_sig

        if not sig:
            # Fallback to global index by tool_call_id (handles session re-keying)
            sig = self._by_tool_call.get(tc_id)
        if not sig:
            # No cached signature available; avoid injecting placeholders that
            # can trigger "corrupted thought signature" errors.
            return

        # Inject the signature
        if isinstance(tc, dict):
            tc["extra_content"] = {"google": {"thought_signature": sig}}
        elif hasattr(tc, "extra_content"):
            tc.extra_content = {"google": {"thought_signature": sig}}

        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(
                TRACE_LEVEL,
                "Injected thought_signature for tool_call_id=%s (session=%s)",
                tc_id,
                session_id[:8] if session_id else "none",
            )

    def store_signatures_from_tool_calls(
        self,
        tool_calls: list[dict[str, Any]],
        session_id: str | None,
    ) -> None:
        """Store thought_signatures from streaming tool call responses.

        Args:
            tool_calls: List of tool call dictionaries with potential signatures
            session_id: The session ID for cache key construction
        """
        anonymous_key = None if session_id else "anon"
        current_time = time.time()

        # Clean expired entries first
        self._clean_expired_entries(current_time)

        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue

            tc_id = tc.get("id", "")
            extra = tc.get("extra_content")
            if not isinstance(extra, dict):
                continue

            google_extra = extra.get("google", {})
            sig = google_extra.get("thought_signature")
            if not sig or not tc_id:
                continue

            cache_key = (
                f"{session_id}:{tc_id}" if session_id else f"{anonymous_key}:{tc_id}"
            )
            if cache_key:
                # Store with timestamp for TTL
                self._cache[cache_key] = (sig, current_time)
                self._by_tool_call[tc_id] = sig

                # Move to end for LRU
                self._cache.move_to_end(cache_key)

                # Enforce size limit
                if len(self._cache) > self._max_cache_size:
                    oldest_key, oldest_value = self._cache.popitem(last=False)
                    oldest_sig, _ = oldest_value
                    # Remove from secondary index too
                    self._by_tool_call = {
                        k: v
                        for k, v in self._by_tool_call.items()
                        if v != oldest_sig
                        or any(k2.endswith(f":{k}") for k2 in self._cache)
                    }

                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Stored thought_signature for tool_call_id=%s (key=%s, cache_size=%d)",
                        tc_id,
                        cache_key[:16],
                        len(self._cache),
                    )

    def log_signature_state(
        self,
        canonical_request: Any,
        session_id: str,
        effective_model: str,
    ) -> None:
        """Log presence/absence of thought signatures on assistant tool calls."""
        if not logger.isEnabledFor(logging.INFO):
            return

        try:
            tool_call_summaries: list[tuple[str, bool, str]] = []
            for message in getattr(canonical_request, "messages", []) or []:
                if getattr(message, "role", None) != "assistant":
                    continue
                tool_calls = getattr(message, "tool_calls", None) or []
                for tc in tool_calls:
                    tc_id = None
                    if isinstance(tc, dict):
                        tc_id = tc.get("id")
                        extra_content = tc.get("extra_content")
                    else:
                        tc_id = getattr(tc, "id", None)
                        extra_content = getattr(tc, "extra_content", None)

                    sig = None
                    if isinstance(extra_content, dict):
                        sig = (
                            extra_content.get("google", {})
                            if isinstance(extra_content.get("google", {}), dict)
                            else {}
                        ).get("thought_signature") or extra_content.get(
                            "thought_signature"
                        )

                    tool_call_summaries.append(
                        (
                            str(tc_id) if tc_id else "unknown",
                            bool(sig),
                            str(sig)[:12] if sig else "none",
                        )
                    )

            logger.info(
                "Thought signature state: session=%s model=%s tool_calls=%d details=%s",
                session_id[:8] if session_id else "none",
                effective_model,
                len(tool_call_summaries),
                tool_call_summaries[:5],
            )
        except Exception:
            logger.debug("Failed to log tool call signature state", exc_info=True)

    def _clean_expired_entries(self, current_time: float | None = None) -> int:
        """Remove expired entries from cache.

        Args:
            current_time: Current timestamp (defaults to time.time())

        Returns:
            Number of entries removed
        """
        if current_time is None:
            current_time = time.time()

        expired_keys = [
            key
            for key, (_, timestamp) in self._cache.items()
            if current_time - timestamp > self._ttl_seconds
        ]

        for key in expired_keys:
            # Get signature before removing to clean up secondary index
            entry = self._cache.get(key)
            if entry:
                sig, _ = entry
                # Remove from secondary index
                self._by_tool_call = {
                    k: v
                    for k, v in self._by_tool_call.items()
                    if v != sig or any(k2.endswith(f":{k}") for k2 in self._cache)
                }
            del self._cache[key]

        return len(expired_keys)

    def clear_all_anonymous(self) -> int:
        """Clear all anonymous cached signatures (session_id was None).

        Returns:
            Number of entries cleared from cache
        """
        keys_to_remove = [key for key in self._cache if key.startswith("anon:")]

        for key in keys_to_remove:
            entry = self._cache.pop(key)
            if entry:
                sig, _ = entry
                # Remove from secondary index
                self._by_tool_call = {
                    k: v
                    for k, v in self._by_tool_call.items()
                    if v != sig or any(k2.endswith(f":{k}") for k2 in self._cache)
                }

        if keys_to_remove and logger.isEnabledFor(logging.INFO):
            logger.info(
                "Cleared %d anonymous thought_signature(s)",
                len(keys_to_remove),
            )

        return len(keys_to_remove)

    def clear_session_cache(self, session_id: str) -> int:
        """Clear all cached signatures for a session.

        Used when switching backends mid-session to prevent incompatible
        thought signatures from being injected into requests to be new backend.

        Args:
            session_id: The session ID prefix to match and clear

        Returns:
            Number of entries cleared from cache
        """
        if not session_id:
            return 0

        prefix = f"{session_id}:"
        keys_to_remove: list[str] = [
            key for key in self._cache if key.startswith(prefix)
        ]

        # Also collect tool_call_ids to remove from secondary index
        tool_call_ids_to_remove: list[str] = []
        for key in keys_to_remove:
            # Key format is "session_id:tool_call_id"
            parts = key.split(":", 1)
            if len(parts) == 2:
                tool_call_ids_to_remove.append(parts[1])

        # Remove from primary cache
        for key in keys_to_remove:
            del self._cache[key]

        # Remove from secondary index
        for tc_id in tool_call_ids_to_remove:
            self._by_tool_call.pop(tc_id, None)

        if keys_to_remove and logger.isEnabledFor(logging.INFO):
            logger.info(
                "Cleared %d thought_signature(s) for session %s",
                len(keys_to_remove),
                session_id[:8] if session_id else "none",
            )

        return len(keys_to_remove)


# Global instance for backward compatibility with class-level cache
_global_thought_signature_manager = ThoughtSignatureManager()


def get_global_thought_signature_manager() -> ThoughtSignatureManager:
    """Get the global thought signature manager instance."""
    return _global_thought_signature_manager
