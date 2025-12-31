"""Context injection middleware for ProxyMem feature.

Injects relevant historical context into new sessions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.domain.chat import ChatMessage, ChatRequest
    from src.core.interfaces.memory_service_interface import IMemoryService
    from src.core.memory.config import MemoryConfiguration
    from src.core.memory.context_injector import ContextInjector

    _ = IMemoryService  # vulture: ignore

logger = logging.getLogger(__name__)


class ContextInjectionMiddleware:
    """Middleware for injecting historical context into requests."""

    def __init__(
        self,
        memory_service: IMemoryService,
        context_injector: ContextInjector,
        config: MemoryConfiguration,
    ):
        """Initialize the context injection middleware.

        Args:
            memory_service: The memory service for state checks.
            context_injector: The context injector for building context.
            config: Memory configuration.
        """
        self._memory_service = memory_service
        self._context_injector = context_injector
        self._config = config
        self._injected_sessions: set[str] = set()

    async def maybe_inject_context(
        self,
        session_id: str,
        request: ChatRequest,
        *,
        user_prompt: str | None = None,
    ) -> ChatRequest:
        """Inject context into request if appropriate.

        Context is only injected for the first request in a session.

        Args:
            session_id: The session identifier.
            request: The incoming chat request.
            user_prompt: Optional user prompt for relevance matching.

        Returns:
            The request, potentially with context injected.
        """
        if not self._memory_service.is_available():
            return request

        if not await self._memory_service.is_enabled_for_session(session_id):
            return request

        # Only inject once per session
        if session_id in self._injected_sessions:
            return request

        user_id = await self._memory_service.get_session_user_id(session_id)
        if not user_id:
            logger.debug(
                "No user_id for session %s, skipping context injection", session_id
            )
            return request

        # Check project discovery gating
        project_root = await self._memory_service.get_session_project_root(session_id)
        if self._config.require_project_discovery and not project_root:
            logger.debug(
                "Project root required but not discovered for session %s, skipping context",
                session_id,
            )
            return request

        # Extract first user message for relevance matching
        if user_prompt is None:
            user_prompt = self._extract_first_user_prompt(request)

        if not user_prompt:
            logger.debug(
                "No user prompt found for session %s, skipping context", session_id
            )
            return request

        # Get session state to retrieve tenant_id and project_id
        state = await self._memory_service.get_session_state(session_id)
        tenant_id = state.tenant_id if state else None
        project_id = state.project_id if state else None

        try:
            context = await self._context_injector.get_context_for_session(
                user_id=user_id,
                current_prompt=user_prompt,
                tenant_id=tenant_id,
                project_id=project_id,
                project_root=project_root,
            )

            # Format context for injection (includes NO_PRIOR_CONTEXT marker if None)
            # Per Req 8.11: Always inject marker when no context available
            formatted_context = self._context_injector.format_context_for_injection(
                context
            )

            if not formatted_context:
                self._injected_sessions.add(session_id)
                return request

            # Log what we're injecting
            if not context:
                logger.debug(
                    "Injecting no-context marker for session %s (no relevant context)",
                    session_id,
                )

            # Inject context into messages
            modified_messages = self._inject_into_messages(
                list(request.messages), formatted_context
            )

            self._injected_sessions.add(session_id)

            logger.info(
                "Injected context for session %s (user=%s, project=%s)",
                session_id,
                user_id,
                project_root or "any",
            )

            return request.model_copy(update={"messages": modified_messages})

        except Exception as e:
            logger.warning(
                "Failed to inject context for session %s: %s",
                session_id,
                e,
                exc_info=True,
            )
            self._injected_sessions.add(session_id)
            return request

    def _extract_first_user_prompt(self, request: ChatRequest) -> str | None:
        """Extract the first user message content from request."""
        for message in request.messages:
            role = getattr(message, "role", None)
            if isinstance(role, str) and role.lower() == "user":
                content = getattr(message, "content", None)
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, str):
                            return part
                        if isinstance(part, dict):
                            text_val = part.get("text")
                            if isinstance(text_val, str):
                                return text_val
                        # Handle object with text attribute safely
                        if hasattr(part, "text"):
                            text_attr = getattr(part, "text", None)
                            if isinstance(text_attr, str):
                                return text_attr
        return None

    def _inject_into_messages(
        self,
        messages: list[ChatMessage],
        context: str,
    ) -> list[ChatMessage]:
        """Inject context as a message after system, before first user.

        Args:
            messages: The original message list.
            context: The formatted context to inject.

        Returns:
            Modified message list with context injected.
        """
        from src.core.domain.chat import ChatMessage

        # Find insertion point: after system messages, before first user
        insert_idx = 0
        for i, msg in enumerate(messages):
            role = getattr(msg, "role", None)
            if isinstance(role, str):
                if role.lower() == "system":
                    insert_idx = i + 1
                elif role.lower() == "user":
                    insert_idx = i
                    break

        # Create context message as user role (common pattern for injection)
        context_message = ChatMessage(
            role="user",
            content=f"[Prior Session Context]\n{context}",
        )

        result = list(messages)
        result.insert(insert_idx, context_message)
        return result

    def clear_session(self, session_id: str) -> None:
        """Clear injection state for a session.

        Call when session ends or memory is disabled.

        Args:
            session_id: The session identifier.
        """
        self._injected_sessions.discard(session_id)
