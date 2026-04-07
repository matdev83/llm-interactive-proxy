"""Auxiliary request routing service.

This module provides detection and routing of auxiliary requests (title generation,
summarization, etc.) to alternative backends to avoid rate limiting on the primary
backend used for main conversation requests.

Clients like OpenCode send multiple parallel requests:
1. Main conversation request (should use primary/powerful backend)
2. Title generation request (can use faster/cheaper backend)
3. Summary generation request (can use faster/cheaper backend)

By routing auxiliary requests to a different backend, we reduce rate limiting
pressure on the primary backend.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from src.core.domain.chat import ChatRequest
from src.core.domain.model_utils import (
    has_explicit_backend_selector,
    parse_model_backend,
)

logger = logging.getLogger(__name__)


def _parse_explicit_backend_target(
    model_selector: str | None,
) -> tuple[str, str] | None:
    """Parse explicit backend:model selector if present and valid."""
    if not isinstance(model_selector, str) or not model_selector:
        return None
    if not has_explicit_backend_selector(model_selector):
        return None

    parsed = parse_model_backend(model_selector, "")
    backend = parsed.backend_type.strip()
    model = parsed.model_name.strip()
    if not backend or not model:
        return None
    return backend, model


@dataclass
class AuxiliaryRoutingConfig:
    """Configuration for auxiliary request routing.

    Attributes:
        enabled: Whether auxiliary request routing is enabled
        backend: Backend to use for auxiliary requests (e.g., "gemini-flash", "openrouter")
        model: Model to use on the auxiliary backend (optional, uses backend default if not set)
        detection_patterns: List of regex patterns to detect auxiliary requests
        max_message_count: Maximum message count for a request to be considered auxiliary
    """

    enabled: bool = False
    backend: str | None = None
    model: str | None = None
    detection_patterns: list[str] = field(
        default_factory=lambda: [
            r"The following is the text to summarize",
            r"Generate a (?:short |brief )?(?:title|summary|heading)",
            r"\b(?:title|summary) generator\b",
            r"Summarize (?:the|this|my) (?:conversation|text|content|task)",
            r"Create a (?:title|heading) for",
            r"Generate a title for the (?:session|conversation)",
            r"Provide a summary of (?:the|this|my) (?:task|conversation|session)",
        ]
    )
    max_message_count: int = 3  # Auxiliary requests typically have few messages


class AuxiliaryRequestDetector:
    """Detects auxiliary requests that can be routed to alternative backends.

    Auxiliary requests are identified by:
    1. Content patterns (summarization, title generation prompts)
    2. Low message count (auxiliary requests typically have 2-3 messages)
    """

    def __init__(self, config: AuxiliaryRoutingConfig) -> None:
        """Initialize the detector.

        Args:
            config: Configuration for auxiliary request detection
        """
        self._config = config
        self._compiled_patterns: list[re.Pattern[str]] = []

        if config.enabled:
            for pattern in config.detection_patterns:
                try:
                    self._compiled_patterns.append(re.compile(pattern, re.IGNORECASE))
                except re.error as e:
                    logger.warning(
                        "Invalid auxiliary detection pattern '%s': %s",
                        pattern,
                        e,
                    )

    def is_auxiliary_request(self, request: ChatRequest) -> bool:
        """Check if a request is an auxiliary request (title/summary generation).

        Args:
            request: The chat request to check

        Returns:
            True if the request is detected as auxiliary, False otherwise
        """
        if not self._config.enabled:
            return False

        # Check if we have a valid routing target (explicit backend or FQN model)
        if not self._config.backend and not _parse_explicit_backend_target(
            self._config.model
        ):
            return False

        messages = getattr(request, "messages", None)
        if not messages:
            return False

        detection_messages = self._filter_detection_messages(messages)

        # Check message count threshold using only system/user messages.
        # OpenCode title requests may include assistant/tool messages from the
        # thing being titled, but only a small number of system/user messages
        # that carry the title-generation instruction itself.
        if len(detection_messages) > self._config.max_message_count:
            return False

        # Check content patterns across the message set.
        #
        # Some clients (e.g., OpenCode) structure auxiliary title requests as:
        #   system: "You are a title generator..."
        #   user: "Generate a title for this conversation:"
        #   user: "<user's last utterance>"
        #
        # If we only scan the last user message, we miss the "Generate a title"
        # marker. Use a combined scan over system/user messages while keeping the
        # strict max_message_count guard to avoid accidental routing of full chats.
        detection_text = self._extract_detection_text(detection_messages)
        if not detection_text:
            return False

        for pattern in self._compiled_patterns:
            if pattern.search(detection_text):
                return True

        return False

    def _filter_detection_messages(self, messages: list[Any]) -> list[Any]:
        """Return only system/user messages relevant to auxiliary detection."""

        filtered: list[Any] = []
        for msg in messages:
            role = getattr(msg, "role", None) or (
                msg.get("role") if isinstance(msg, dict) else None
            )
            if role in {"system", "user"}:
                filtered.append(msg)
        return filtered

    def _extract_detection_text(self, messages: list[Any]) -> str | None:
        """Extract a combined text blob for auxiliary detection.

        Args:
            messages: List of chat messages

        Returns:
            Concatenated text content from system and user messages, or None
        """
        text_parts: list[str] = []

        for msg in messages:
            content = getattr(msg, "content", None) or (
                msg.get("content") if isinstance(msg, dict) else None
            )
            if isinstance(content, str):
                if content:
                    text_parts.append(content)
                continue

            if isinstance(content, list):
                # Handle multipart content (OpenAI-style)
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text" and isinstance(
                            part.get("text"), str
                        ):
                            text_parts.append(part.get("text", ""))
                    elif isinstance(part, str):
                        text_parts.append(part)

        if not text_parts:
            return None
        return "\n".join(text_parts)

    def get_auxiliary_target(self) -> tuple[str, str | None]:
        """Get the target backend and model for auxiliary requests.

        Returns:
            Tuple of (backend, model) where model may be None
        """
        backend = self._config.backend
        model = self._config.model
        if not backend:
            parsed = _parse_explicit_backend_target(model)
            if parsed is not None:
                backend, model = parsed
        return (backend or "", model)


class AuxiliaryRequestRouter:
    """Routes auxiliary requests to alternative backends.

    This service integrates with the request processing pipeline to detect
    auxiliary requests and modify the target backend/model before the request
    is processed.
    """

    def __init__(self, config: AuxiliaryRoutingConfig) -> None:
        """Initialize the router.

        Args:
            config: Configuration for auxiliary request routing
        """
        self._config = config
        self._detector = AuxiliaryRequestDetector(config)
        self._auxiliary_request_count = 0
        self._total_request_count = 0

    @property
    def enabled(self) -> bool:
        """Check if auxiliary routing is enabled."""
        if not self._config.enabled:
            return False
        return bool(self.get_auxiliary_backend())

    def should_route_to_auxiliary(self, request: ChatRequest) -> bool:
        """Check if a request should be routed to the auxiliary backend.

        Args:
            request: The chat request to check

        Returns:
            True if the request should use the auxiliary backend
        """
        self._total_request_count += 1
        is_auxiliary = self._detector.is_auxiliary_request(request)
        if is_auxiliary:
            self._auxiliary_request_count += 1
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Routing auxiliary request to backend '%s' (aux: %d / total: %d)",
                    self.get_auxiliary_backend(),
                    self._auxiliary_request_count,
                    self._total_request_count,
                )
        return is_auxiliary

    def get_auxiliary_backend(self) -> str:
        """Get the effective auxiliary backend name.

        Returns:
            The auxiliary backend name
        """
        backend, _ = self._detector.get_auxiliary_target()
        return backend

    def get_auxiliary_model(self) -> str | None:
        """Get the effective auxiliary model name.

        Returns:
            The auxiliary model name, or None to use backend default
        """
        _, model = self._detector.get_auxiliary_target()
        return model

    def modify_request_for_auxiliary(
        self, request: ChatRequest
    ) -> tuple[ChatRequest, str, str | None]:
        """Modify a request to use the auxiliary backend.

        Args:
            request: The original chat request

        Returns:
            Tuple of (modified_request, backend, model)
        """
        backend = self.get_auxiliary_backend()
        model = self.get_auxiliary_model()

        # If a specific model is configured, update the request
        if model and hasattr(request, "model"):
            request.model = model

        return (request, backend, model)

    def get_stats(self) -> dict[str, Any]:
        """Get routing statistics.

        Returns:
            Dictionary with routing statistics
        """
        return {
            "enabled": self.enabled,
            "auxiliary_backend": self.get_auxiliary_backend(),
            "auxiliary_model": self.get_auxiliary_model(),
            "auxiliary_request_count": self._auxiliary_request_count,
            "total_request_count": self._total_request_count,
            "auxiliary_percentage": (
                round(
                    self._auxiliary_request_count / self._total_request_count * 100, 1
                )
                if self._total_request_count > 0
                else 0.0
            ),
        }
