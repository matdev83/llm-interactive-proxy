"""Memory capture middleware for ProxyMem feature.

Captures user prompts and assistant responses for enabled sessions.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, cast

from src.core.memory.config import MemoryConfiguration
from src.core.memory.models import CapturedInteraction

if TYPE_CHECKING:
    from src.core.domain.chat import ChatMessage, ChatRequest
    from src.core.interfaces.memory_service_interface import IMemoryService

    _ = IMemoryService  # vulture: ignore

logger = logging.getLogger(__name__)


class MemoryCaptureMiddleware:
    """Middleware for capturing interactions in memory-enabled sessions."""

    def __init__(
        self,
        memory_service: IMemoryService,
        config: MemoryConfiguration | None = None,
    ):
        """Initialize the memory capture middleware.

        Args:
            memory_service: The memory service for capturing interactions.
            config: Optional memory configuration for auto-enable feature.
        """
        self._memory_service = memory_service
        self._config = config
        self._auto_enabled_sessions: set[str] = set()

    async def capture_request(
        self,
        session_id: str,
        request: ChatRequest,
        *,
        user_id: str | None = None,
        client_id: str | None = None,
        tenant_id: str | None = None,
        project_root: str | None = None,
    ) -> None:
        """Capture user messages from request.

        Per Req 2.1: If memory_available and default_enabled are true,
        auto-enables memory for new sessions.

        Args:
            session_id: The session identifier.
            request: The incoming chat request.
            user_id: Optional user identifier for auto-enabling.
            client_id: Optional client identifier for auto-enabling.
            tenant_id: Optional tenant identifier for auto-enabling.
            project_root: Optional project root for auto-enabling.
        """
        if not self._memory_service.is_available():
            return

        # Check if session already enabled or auto-enable based on default_enabled
        is_enabled = await self._memory_service.is_enabled_for_session(session_id)

        # Try auto-enable if default_enabled is True (Req 2.1)
        should_auto_enable = (
            not is_enabled
            and self._config
            and self._config.default_enabled
            and session_id not in self._auto_enabled_sessions
            and user_id
        )
        if should_auto_enable:
            self._auto_enabled_sessions.add(session_id)
            enabled = await self._memory_service.enable_for_session(
                session_id,
                cast(str, user_id),
                client_id=client_id,
                tenant_id=tenant_id,
                project_root=project_root,
            )
            if enabled:
                logger.info(
                    "Auto-enabled memory for session %s (default_enabled=True)",
                    session_id,
                )
                is_enabled = True
            else:
                logger.debug(
                    "Auto-enable failed for session %s (denied or unavailable)",
                    session_id,
                )

        if not is_enabled:
            return

        # Capture user messages from the request
        for message in request.messages:
            if self._is_user_message(message):
                content = self._extract_content(message)
                if content:
                    interaction = CapturedInteraction(
                        role="user",
                        content=content,
                        timestamp=datetime.now(timezone.utc),
                        metadata={
                            "model": request.model,
                        },
                    )
                    success = await self._memory_service.capture_interaction(
                        session_id, interaction
                    )
                    if not success:
                        logger.warning(
                            "Failed to capture user message for session %s",
                            session_id,
                        )

    async def capture_response(
        self,
        session_id: str,
        content: str,
        *,
        backend: str | None = None,
        model: str | None = None,
        tokens_used: int | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> None:
        """Capture assistant response.

        Args:
            session_id: The session identifier.
            content: The response content.
            backend: Optional backend identifier.
            model: Optional model identifier.
            tokens_used: Optional token usage count.
            tool_calls: Optional list of tool calls.
        """
        if not self._memory_service.is_available():
            return

        if not await self._memory_service.is_enabled_for_session(session_id):
            return

        if not content and not tool_calls:
            return

        metadata: dict[str, Any] = {}
        if backend:
            metadata["backend"] = backend
        if model:
            metadata["model"] = model
        if tokens_used is not None:
            metadata["tokens_used"] = tokens_used
        if tool_calls:
            metadata["tool_calls"] = tool_calls

        interaction = CapturedInteraction(
            role="assistant",
            content=content,
            timestamp=datetime.now(timezone.utc),
            metadata=metadata,
        )

        success = await self._memory_service.capture_interaction(
            session_id, interaction
        )
        if not success:
            logger.warning(
                "Failed to capture assistant response for session %s",
                session_id,
            )

    def _is_user_message(self, message: ChatMessage) -> bool:
        """Check if message is from user."""
        role = getattr(message, "role", None)
        if isinstance(role, str):
            return role.lower() == "user"
        return False

    def _extract_content(self, message: ChatMessage) -> str:
        """Extract text content from message."""
        content = getattr(message, "content", None)
        if content is None:
            return ""

        if isinstance(content, str):
            return content

        # Handle list of content parts (e.g., for multimodal)
        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, str):
                    text_parts.append(part)
                elif isinstance(part, dict):
                    text = part.get("text", "")
                    if text:
                        text_parts.append(text)
                elif hasattr(part, "text"):
                    text = getattr(part, "text", "")
                    if text:
                        text_parts.append(text)
            return "\n".join(text_parts)

        return str(content)
