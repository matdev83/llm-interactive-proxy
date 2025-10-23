"""
Service for computing conversation fingerprints from message history.

This service creates stable, deterministic fingerprints that can identify
conversation continuity even when clients don't send session IDs.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from src.core.domain.chat import ChatMessage

logger = logging.getLogger(__name__)


@dataclass
class ConversationFingerprint:
    """Represents a conversation fingerprint with metadata."""

    fingerprint: str
    message_count: int
    last_role: str | None = None


class ConversationFingerprintService:
    """Service for computing stable fingerprints from message sequences."""

    def __init__(self, fingerprint_message_count: int = 5) -> None:
        """Initialize the fingerprint service.

        Args:
            fingerprint_message_count: Number of recent messages to include in fingerprint
        """
        self._fingerprint_message_count = fingerprint_message_count

    def compute_fingerprint(
        self, messages: list[ChatMessage], count: int | None = None
    ) -> ConversationFingerprint:
        """Compute a stable fingerprint from message sequence.

        Args:
            messages: List of messages to fingerprint
            count: Number of messages to use (default: configured count)

        Returns:
            ConversationFingerprint object with hash and metadata
        """
        if not messages:
            return ConversationFingerprint(
                fingerprint="empty", message_count=0, last_role=None
            )

        # Use last N messages for fingerprint
        num_messages = count if count is not None else self._fingerprint_message_count
        relevant_messages = (
            messages[-num_messages:] if len(messages) > num_messages else messages
        )

        # Build fingerprint string
        parts = []
        for idx, msg in enumerate(relevant_messages):
            role = msg.role
            content = self._extract_content_preview(msg)
            # Include position to maintain order sensitivity
            parts.append(f"{idx}:{role}:{content}")

        fingerprint_str = "|".join(parts)
        hash_obj = hashlib.sha256(fingerprint_str.encode("utf-8"))
        fingerprint_hex = hash_obj.hexdigest()[:32]

        return ConversationFingerprint(
            fingerprint=fingerprint_hex,
            message_count=len(relevant_messages),
            last_role=relevant_messages[-1].role if relevant_messages else None,
        )

    def compute_rolling_fingerprints(
        self, messages: list[ChatMessage], window_size: int = 3
    ) -> list[str]:
        """Compute fingerprints for sliding windows of messages.

        Useful for fuzzy matching to detect if current conversation
        contains messages from a previous session.

        Args:
            messages: List of messages
            window_size: Size of sliding window

        Returns:
            List of fingerprint hashes
        """
        if len(messages) < window_size:
            return []

        fingerprints = []
        for i in range(len(messages) - window_size + 1):
            window = messages[i : i + window_size]
            fp = self.compute_fingerprint(window, count=window_size)
            fingerprints.append(fp.fingerprint)

        return fingerprints

    def _extract_content_preview(
        self, message: ChatMessage, max_length: int = 200
    ) -> str:
        """Extract a preview of message content for fingerprinting.

        Args:
            message: Message to extract content from
            max_length: Maximum length of preview

        Returns:
            Content preview string
        """
        content = message.content

        # Handle None content
        if content is None:
            # Check for tool calls
            if message.tool_calls:
                tool_names = [tc.function.name for tc in message.tool_calls]
                return f"tool_calls:{','.join(tool_names)}"
            return "empty"

        # Handle string content
        if isinstance(content, str):
            # Normalize whitespace
            normalized = " ".join(content.split())
            # Truncate to max length
            preview = (
                normalized[:max_length] if len(normalized) > max_length else normalized
            )
            return preview

        # Handle list of content parts (multimodal)
        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text" and "text" in part:
                        text_parts.append(part["text"])
                    elif part.get("type") == "image_url":
                        text_parts.append("[image]")
                elif hasattr(part, "type"):
                    if part.type == "text" and hasattr(part, "text"):
                        text_parts.append(part.text)
                    elif part.type == "image_url":
                        text_parts.append("[image]")

            combined = " ".join(text_parts)
            normalized = " ".join(combined.split())
            preview = (
                normalized[:max_length] if len(normalized) > max_length else normalized
            )
            return preview if preview else "multimodal"

        # Fallback for unexpected content types
        return str(content)[:max_length]

    def is_continuation(
        self,
        previous_messages: list[ChatMessage],
        current_messages: list[ChatMessage],
        min_overlap: int = 3,
    ) -> bool:
        """Check if current messages are a continuation of previous messages.

        Args:
            previous_messages: Messages from a previous session
            current_messages: Messages from current request
            min_overlap: Minimum number of overlapping messages required

        Returns:
            True if current is a continuation of previous
        """
        if not previous_messages or not current_messages:
            return False

        # Current should have more messages than previous
        if len(current_messages) <= len(previous_messages):
            return False

        # Check if the last N messages from previous session
        # match the corresponding messages in current session
        check_count = min(len(previous_messages), min_overlap)
        prev_check = previous_messages[-check_count:]
        curr_check = current_messages[
            len(previous_messages) - check_count : len(previous_messages)
        ]

        if len(prev_check) != len(curr_check):
            return False

        # Compare fingerprints of the overlapping sections
        prev_fp = self.compute_fingerprint(prev_check, count=len(prev_check))
        curr_fp = self.compute_fingerprint(curr_check, count=len(curr_check))

        return prev_fp.fingerprint == curr_fp.fingerprint
