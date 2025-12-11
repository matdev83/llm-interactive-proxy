"""
Thought signature management for Gemini Code Assist.

This module handles server-side storage and injection of thought_signatures
for clients (like Droid) that don't preserve extra_content.
"""

import base64
import hashlib
import logging
from typing import Any

from src.core.app.constants.logging_constants import TRACE_LEVEL

logger = logging.getLogger(__name__)


class ThoughtSignatureManager:
    """Manages thought signatures for tool calls.

    Droid and similar clients don't preserve extra_content, so we store
    the mapping of tool_call_id -> thought_signature server-side and
    inject it when processing subsequent requests.

    Key format: "session_id:tool_call_id" -> thought_signature
    """

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}

    @property
    def cache(self) -> dict[str, str]:
        """Access the cache for backward compatibility."""
        return self._cache

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

        # Look up in cache
        cache_key = f"{session_id}:{tc_id}"
        sig = self._cache.get(cache_key)
        if not sig:
            # Try anonymous cache if session_id was missing at store time
            sig = self._cache.get(f"anon:{tc_id}")
        if not sig:
            # Generate a deterministic placeholder signature
            sig = self._generate_placeholder_signature(cache_key)
            self._cache[cache_key] = sig

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

    def _generate_placeholder_signature(self, cache_key: str) -> str:
        """Generate a deterministic placeholder signature.

        Uses base64url-encoded bytes to match expected format.
        """
        sig_bytes = hashlib.sha256(cache_key.encode()).digest()[:16]
        return base64.urlsafe_b64encode(sig_bytes).decode("ascii").rstrip("=")

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
                self._cache[cache_key] = sig
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Stored thought_signature for tool_call_id=%s (key=%s)",
                        tc_id,
                        cache_key[:16],
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


# Global instance for backward compatibility with class-level cache
_global_thought_signature_manager = ThoughtSignatureManager()


def get_global_thought_signature_manager() -> ThoughtSignatureManager:
    """Get the global thought signature manager instance."""
    return _global_thought_signature_manager
