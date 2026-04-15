"""
Session manager implementation.

This module provides the implementation of the session manager interface.
"""

from __future__ import annotations

# mypy: disable-error-code="unreachable"
import logging

from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session import Session, SessionInteraction
from src.core.interfaces.repositories_interface import ISessionRepository
from src.core.interfaces.session_manager_interface import ISessionManager
from src.core.interfaces.session_resolver_interface import ISessionResolver
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.conversation_fingerprint_service import (
    ConversationFingerprintService,
)
from src.core.services.fingerprint_request_transformer import (
    apply_fingerprint_transforms,
)

logger = logging.getLogger(__name__)

_OPENAI_CODEX_BACKEND_FAMILY = "openai-codex"


def _normalize_backend_family_for_history_compaction(backend: str | None) -> str:
    """Match multi-instance backends (e.g. openai-codex.1) to their family name."""
    if not isinstance(backend, str) or not backend.strip():
        return ""
    normalized = backend.strip().lower().replace("_", "-")
    if "." in normalized:
        normalized = normalized.split(".", 1)[0]
    return normalized


class SessionManager(ISessionManager):
    """Implementation of the session manager."""

    def __init__(
        self,
        session_service: ISessionService,
        session_resolver: ISessionResolver,
        fingerprint_service: ConversationFingerprintService,
        session_repository: ISessionRepository | None = None,
    ) -> None:
        """Initialize the session manager."""
        self._session_service = session_service
        self._session_resolver = session_resolver
        self._session_repository = session_repository
        self._fingerprint_service = fingerprint_service

    async def resolve_session_id(self, context: RequestContext) -> str:
        """Resolve session ID from request context."""
        return await self._session_resolver.resolve_session_id(context)

    async def get_session(self, session_id: str) -> Session:
        """Get session by ID."""
        return await self._session_service.get_session(session_id)

    async def apply_openai_codex_history_compaction_gate(
        self, session: Session, resolved_backend: str | None
    ) -> Session:
        """See ``ISessionManager.apply_openai_codex_history_compaction_gate``."""
        # Unit/integration tests often pass lightweight stand-ins instead of ``Session``.
        if not isinstance(session, Session):
            return session

        family = _normalize_backend_family_for_history_compaction(resolved_backend)
        if family != _OPENAI_CODEX_BACKEND_FAMILY:
            return session
        if not session.state.history_compaction_allowed:
            return session

        new_state = session.state.with_history_compaction_allowed(False)
        session.update_state(new_state)
        try:
            await self._session_service.update_session(session)
        except Exception as exc:
            session.update_state(session.state.with_history_compaction_allowed(True))
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to persist history compaction disable for session %s; "
                    "reverted in-memory flag so storage stays consistent "
                    "(openai-codex gate will retry on a later request): %s",
                    session.session_id,
                    exc,
                    exc_info=True,
                )
            return session
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Disabled history context compaction for the remainder of this session "
                "because the openai-codex backend was selected (session_id=%s).",
                session.session_id,
            )
        return session

    async def update_session_agent(
        self, session: Session, agent: str | None
    ) -> Session:
        """Update session agent and return updated session."""
        if agent is not None and agent != session.agent:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Setting session agent from request_data: {agent}")
            session.agent = agent
            await self._session_service.update_session(session)
            # Re-fetch to ensure latest state
            session = await self._session_service.get_session(session.id)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Session object ID after re-fetch: {id(session)}")
        return session

    async def record_command_in_session(
        self, request_data: ChatRequest, session_id: str
    ) -> None:
        """Record a command-only request in the session history."""
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"SessionManager.record_command_in_session called for session {session_id}"
            )
        session = await self._session_service.get_session(session_id)

        def _extract_role_and_content(
            message: object,
        ) -> tuple[str | None, object | None]:
            """Best-effort extraction of role/content from heterogeneous message types."""
            # Use Any internally to avoid mypy complaints on duck-typed access
            from typing import Any, cast

            msg_any = cast(Any, message)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Extracting role/content from {type(msg_any).__name__}: {msg_any}"
                )
            # Pydantic models expose model_dump
            if hasattr(msg_any, "model_dump") and callable(msg_any.model_dump):
                try:
                    data = msg_any.model_dump()
                    if isinstance(data, dict):
                        return data.get("role"), data.get("content")
                    return None, None
                except (AttributeError, TypeError, KeyError) as exc:
                    logger.debug(
                        "Failed to extract role/content via model_dump from %s: %s",
                        type(msg_any).__name__,
                        exc,
                        exc_info=True,
                    )
                except Exception as exc:
                    logger.warning(
                        "Unexpected error extracting role/content via model_dump from %s: %s",
                        type(msg_any).__name__,
                        exc,
                        exc_info=True,
                    )
            # Mapping-like messages
            if isinstance(msg_any, dict):
                return msg_any.get("role"), msg_any.get("content")
            # Fallback to attribute access
            return getattr(msg_any, "role", None), getattr(msg_any, "content", None)

        raw_prompt = ""
        if request_data and getattr(request_data, "messages", None):
            for message in reversed(request_data.messages):
                role, content = _extract_role_and_content(message)
                if role == "user":
                    raw_prompt = content if isinstance(content, str) else str(content)
                    break

        if raw_prompt:
            try:
                last = session.history[-1] if session.history else None
                last_prompt = getattr(last, "prompt", None) if last else None
            except (IndexError, AttributeError) as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Could not retrieve last prompt from session history: {e}",
                        exc_info=True,
                    )
                last_prompt = None

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Recording command in session {session_id}: raw_prompt='{raw_prompt}', last_prompt='{last_prompt}'"
                )

            if last_prompt != raw_prompt:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        f"Adding new interaction to session {session_id} (history size before: {len(session.history)})"
                    )
                session.add_interaction(
                    SessionInteraction(
                        prompt=raw_prompt,
                        handler="proxy",
                        backend=getattr(
                            session.state.backend_config, "backend_type", None
                        ),
                        model=getattr(session.state.backend_config, "model", None),
                        project=getattr(session.state, "project", None),
                        parameters={
                            "temperature": getattr(request_data, "temperature", None),
                            "top_p": getattr(request_data, "top_p", None),
                            "max_tokens": getattr(request_data, "max_tokens", None),
                        },
                    )
                )
                await self._session_service.update_session(session)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        f"Interaction added to session {session_id} (history size after: {len(session.history)})"
                    )

    async def update_session_history(
        self,
        request_data: ChatRequest,
        backend_request: ChatRequest,
        backend_response: ResponseEnvelope | StreamingResponseEnvelope,
        session_id: str,
    ) -> None:
        """Update session history with the backend interaction."""
        # BackendProcessor records backend interactions; avoid duplicating entries here.
        # This method is retained for compatibility and future extensions.
        _ = await self._session_service.get_session(session_id)

    async def update_session_fingerprint(
        self,
        session_id: str,
        request: ChatRequest,
        context: RequestContext | None = None,
    ) -> None:
        """Update the conversation fingerprint for a session.

        Args:
            session_id: Session ID to update
            request: Request used to derive fingerprint content
            context: Optional request context for config access
        """
        if not self._session_repository:
            # Repository not available, skip fingerprinting
            return

        if not request or not getattr(request, "messages", None):
            return

        transformed = await apply_fingerprint_transforms(
            request, context=context, session_id=session_id
        )
        messages = list(getattr(transformed, "messages", None) or [])
        if not messages:
            return

        # Compute fingerprint from messages
        fp_bundle = self._fingerprint_service.compute_fingerprint_bundle(messages)

        # Update in repository
        await self._session_repository.update_fingerprint(
            session_id, fp_bundle.primary.fingerprint
        )
        await self._session_repository.update_fingerprint_bundle(session_id, fp_bundle)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Updated fingerprint bundle for session %s: primary=%s message_count=%s "
                "rolling=%s topic_hash=%s",
                session_id,
                fp_bundle.primary.fingerprint,
                fp_bundle.message_count,
                len(fp_bundle.rolling_fingerprints),
                fp_bundle.topic_hash,
            )
