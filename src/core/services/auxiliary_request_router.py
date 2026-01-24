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

logger = logging.getLogger(__name__)


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
    detection_patterns: list[str] = field(default_factory=lambda: [
        r"The following is the text to summarize",
        r"Generate a (?:short |brief )?(?:title|summary|heading)",
        r"Summarize (?:the|this|my) (?:conversation|text|content|task)",
        r"Create a (?:title|heading) for",
        r"Generate a title for the (?:session|conversation)",
        r"Provide a summary of (?:the|this|my) (?:task|conversation|session)",
    ])
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
                    self._compiled_patterns.append(
                        re.compile(pattern, re.IGNORECASE)
                    )
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
        if not self._config.backend and (not self._config.model or ":" not in self._config.model):
            return False

        messages = getattr(request, "messages", None)
        if not messages:
            return False

        # Check message count threshold
        if len(messages) > self._config.max_message_count:
            return False

        # Check content patterns in the last user message
        last_user_content = self._extract_last_user_content(messages)
        if not last_user_content:
            return False

        for pattern in self._compiled_patterns:
            if pattern.search(last_user_content):
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Detected auxiliary request (pattern: %s, msg_count: %d)",
                        pattern.pattern[:50],
                        len(messages),
                    )
                return True

        return False

    def _extract_last_user_content(self, messages: list[Any]) -> str | None:
        """Extract content from the last user message.

        Args:
            messages: List of chat messages

        Returns:
            The text content of the last user message, or None
        """
        for msg in reversed(messages):
            role = getattr(msg, "role", None) or (
                msg.get("role") if isinstance(msg, dict) else None
            )
            if role == "user":
                content = getattr(msg, "content", None) or (
                    msg.get("content") if isinstance(msg, dict) else None
                )
                if isinstance(content, str):
                    return content
                elif isinstance(content, list):
                    # Handle multipart content
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                        elif isinstance(part, str):
                            text_parts.append(part)
                    return " ".join(text_parts) if text_parts else None
        return None

    def get_auxiliary_target(self) -> tuple[str, str | None]:
        """Get the target backend and model for auxiliary requests.

        Returns:
            Tuple of (backend, model) where model may be None
        """
        backend = self._config.backend
        model = self._config.model
        if not backend and model and ":" in model:
            backend, model = model.split(":", 1)
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
        if self._config.backend:
            return self._config.backend
        if self._config.model and ":" in self._config.model:
            return self._config.model.split(":", 1)[0]
        return ""

    def get_auxiliary_model(self) -> str | None:
        """Get the effective auxiliary model name.

        Returns:
            The auxiliary model name, or None to use backend default
        """
        if self._config.backend:
            return self._config.model
        if self._config.model and ":" in self._config.model:
            return self._config.model.split(":", 1)[1]
        return self._config.model

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
