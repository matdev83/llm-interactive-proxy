"""
Intelligent session resolver that uses message history fingerprinting.

This resolver detects conversation continuity without requiring clients
to send session IDs, supporting multiple concurrent conversations per client.
"""

from __future__ import annotations

import hashlib
import logging
from uuid import uuid4

from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.repositories_interface import ISessionRepository
from src.core.interfaces.session_resolver_interface import ISessionResolver
from src.core.services.conversation_fingerprint_service import (
    ConversationFingerprintService,
)

logger = logging.getLogger(__name__)


class IntelligentSessionResolver(ISessionResolver):
    """Session resolver using message history fingerprinting."""

    def __init__(
        self,
        session_repository: ISessionRepository,
        fingerprint_service: ConversationFingerprintService,
        config: IConfig | None = None,
    ) -> None:
        """Initialize the intelligent session resolver.

        Args:
            session_repository: Repository for session storage/retrieval
            fingerprint_service: Fingerprint service for computing conversation hashes
            config: Optional configuration object
        """
        self._session_repository = session_repository
        self._config = config
        self._fingerprint_service = fingerprint_service

        # Load configuration
        self._enabled = True
        self._fuzzy_matching = True
        self._max_session_age_seconds = 604800  # 7 days default
        self._client_key_includes_ip = True

        if config and hasattr(config, "session"):
            session_config = config.session
            if hasattr(session_config, "session_continuity"):
                continuity = session_config.session_continuity
                self._enabled = getattr(continuity, "enabled", True)
                self._fuzzy_matching = getattr(continuity, "fuzzy_matching", True)
                self._max_session_age_seconds = getattr(
                    continuity, "max_session_age_seconds", 604800
                )
                self._client_key_includes_ip = getattr(
                    continuity, "client_key_includes_ip", True
                )

    async def resolve_session_id(self, context: RequestContext) -> str:
        """Resolve session ID using intelligent fingerprinting.

        Resolution priority:
        1. Explicit session ID from headers/cookies
        2. Message history fingerprint matching
        3. Fuzzy matching of conversation continuation
        4. Create new session

        Args:
            context: Request context

        Returns:
            Resolved session ID
        """
        # 1. Try explicit session ID from headers/cookies (highest priority)
        explicit_id = await self._try_explicit_session_id(context)
        if explicit_id:
            logger.debug(f"Using explicit session ID from header/cookie: {explicit_id}")
            return explicit_id

        # If intelligent resolver is disabled, fall back to generating new ID
        if not self._enabled:
            return str(uuid4())

        # 2. Extract client fingerprint
        client_key = self._compute_client_key(context)

        # 3. Extract request messages
        messages = self._extract_messages_from_context(context)

        # 4. If no messages or too few, create new session
        if not messages or len(messages) < 2:
            session_id = str(uuid4())
            logger.info(
                f"Creating new session {session_id} for client {client_key} (insufficient message history)"
            )
            await self._session_repository.update_client_session(session_id, client_key)
            return session_id

        # 5. Compute conversation fingerprint
        fp_result = self._fingerprint_service.compute_fingerprint(messages)
        conversation_fp = fp_result.fingerprint

        logger.debug(
            f"Computed fingerprint {conversation_fp} from {fp_result.message_count} messages"
        )

        # 6. Try exact fingerprint match
        existing_session = (
            await self._session_repository.find_by_client_and_fingerprint(
                client_key, conversation_fp
            )
        )

        if existing_session:
            logger.info(
                f"Detected exact continuation of session {existing_session.id} for client {client_key}"
            )
            return str(existing_session.id)

        # 7. Try fuzzy matching if enabled
        if self._fuzzy_matching:
            fuzzy_match = await self._try_fuzzy_match(client_key, messages)
            if fuzzy_match:
                logger.info(
                    f"Fuzzy matched continuation of session {fuzzy_match} for client {client_key}"
                )
                return fuzzy_match

        # 8. No match found - create new session
        session_id = str(uuid4())
        logger.info(
            f"Created new session {session_id} for client {client_key} (no matching history)"
        )
        await self._session_repository.update_client_session(session_id, client_key)

        return session_id

    async def _try_explicit_session_id(self, context: RequestContext) -> str | None:
        """Try to get explicit session ID from request context.

        Args:
            context: Request context

        Returns:
            Session ID if found, None otherwise
        """
        # Check context attribute
        context_session_id = getattr(context, "session_id", None)
        if isinstance(context_session_id, str) and context_session_id:
            return context_session_id

        # Check headers
        header_value = context.headers.get("x-session-id")
        if isinstance(header_value, str) and header_value:
            return header_value

        # Check cookies
        cookie_value = context.cookies.get("session_id")
        if isinstance(cookie_value, str) and cookie_value:
            return cookie_value

        return None

    def _compute_client_key(self, context: RequestContext) -> str:
        """Compute a stable client identifier.

        Args:
            context: Request context

        Returns:
            Client key string
        """
        components = []

        # Include client host/IP if configured
        if self._client_key_includes_ip:
            client_host = context.client_host
            if isinstance(client_host, str) and client_host:
                components.append(client_host)

        # Include user agent (always)
        user_agent = context.headers.get("user-agent", "unknown")
        if user_agent is not None:
            components.append(user_agent)
        else:
            components.append("unknown")

        # Hash to create stable but anonymized key
        key_str = "|".join(components)
        hash_obj = hashlib.sha256(key_str.encode("utf-8"))
        return hash_obj.hexdigest()[:32]

    def _extract_messages_from_context(
        self, context: RequestContext
    ) -> list[ChatMessage] | None:
        """Extract messages from request context.

        Args:
            context: Request context

        Returns:
            List of messages if found, None otherwise
        """
        # Try to get messages from domain_request if available
        if hasattr(context, "domain_request"):
            domain_request = getattr(context, "domain_request", None)
            if domain_request and isinstance(domain_request, ChatRequest):
                messages = getattr(domain_request, "messages", None)
                if messages:
                    return list(messages)

        return None

    async def _try_fuzzy_match(
        self, client_key: str, messages: list[ChatMessage]
    ) -> str | None:
        """Try fuzzy matching to find continuation session.

        Args:
            client_key: Client identifier
            messages: Current request messages

        Returns:
            Session ID if matched, None otherwise
        """
        # Get recent sessions for this client
        recent_sessions = await self._session_repository.find_recent_sessions_by_client(
            client_key, self._max_session_age_seconds
        )

        if not recent_sessions:
            return None

        # Check each session for continuation
        for session in recent_sessions:
            # Get the stored fingerprint for this session
            session_fp = await self._session_repository.get_session_fingerprint(
                session.id
            )

            if not session_fp:
                continue

            # Try to reconstruct the previous message sequence
            # by computing rolling fingerprints from current messages
            # and checking if any match the session's fingerprint
            # Try multiple window sizes to maximize chance of finding a match
            for window_size in [3, 4, 5, 6]:
                if len(messages) < window_size:
                    continue

                rolling_fps = self._fingerprint_service.compute_rolling_fingerprints(
                    messages, window_size=window_size
                )

                if session_fp in rolling_fps:
                    # Found a match - this is likely a continuation
                    logger.debug(
                        f"Fuzzy match: session {session.id} fingerprint (window={window_size}) found in message history"
                    )
                    return str(session.id)

        return None
