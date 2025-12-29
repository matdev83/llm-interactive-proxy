"""
Intelligent session resolver that uses message history fingerprinting.

This resolver detects conversation continuity without requiring clients
to send session IDs, supporting multiple concurrent conversations per client.
"""

from __future__ import annotations

import hashlib
import logging
import time
from uuid import uuid4

from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.repositories_interface import ISessionRepository
from src.core.interfaces.session_resolver_interface import ISessionResolver
from src.core.services.conversation_fingerprint_service import (
    ConversationFingerprintBundle,
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
        self._topic_similarity_threshold = 0.3
        self._topic_overlap_min_tokens = 10
        self._recent_session_window_seconds = 900

        if config and hasattr(config, "session"):
            session_config = getattr(config, "session", None)  # type: ignore[attr-defined]
            if session_config is not None and hasattr(
                session_config, "session_continuity"
            ):
                continuity = session_config.session_continuity
                self._enabled = getattr(continuity, "enabled", True)
                self._fuzzy_matching = getattr(continuity, "fuzzy_matching", True)
                self._max_session_age_seconds = getattr(
                    continuity, "max_session_age_seconds", 604800
                )
                self._client_key_includes_ip = getattr(
                    continuity, "client_key_includes_ip", True
                )
                self._topic_similarity_threshold = getattr(
                    continuity, "topic_similarity_threshold", 0.3
                )
                self._topic_overlap_min_tokens = getattr(
                    continuity, "topic_overlap_min_tokens", 10
                )
                self._recent_session_window_seconds = getattr(
                    continuity, "recent_session_window_seconds", 900
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
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Using explicit session ID from header/cookie: {explicit_id}"
                )
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
        fp_bundle = self._fingerprint_service.compute_fingerprint_bundle(messages)
        conversation_fp = fp_bundle.primary.fingerprint

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Computed fingerprint bundle primary=%s message_count=%s rolling=%s",
                conversation_fp,
                fp_bundle.message_count,
                len(fp_bundle.rolling_fingerprints),
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
            fuzzy_match = await self._try_fuzzy_match(client_key, fp_bundle)
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
        header_keys = list(context.headers.keys())
        header_value = context.headers.get("x-session-id")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Checking for x-session-id in headers. Found: {bool(header_value)}, Keys: {header_keys}"
            )
        if isinstance(header_value, str) and header_value:
            return header_value

        # Check cookies
        cookie_value = context.cookies.get("session_id")
        if isinstance(cookie_value, str) and cookie_value:
            return cookie_value

        # Check query parameters as a fallback for explicit session ID
        if (
            hasattr(context, "original_request")
            and context.original_request is not None
            and hasattr(context.original_request, "query_params")
        ):
            query_param_value = context.original_request.query_params.get("session_id")
            if isinstance(query_param_value, str) and query_param_value:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        f"Found session ID in query parameters: {query_param_value}"
                    )
                return query_param_value

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
        self,
        client_key: str,
        bundle: ConversationFingerprintBundle,
    ) -> str | None:
        """Try fuzzy matching to find continuation session.

        Args:
            client_key: Client identifier
            bundle: Incoming fingerprint bundle

        Returns:
            Session ID if matched, None otherwise
        """
        recent_sessions = await self._session_repository.find_recent_sessions_by_client(
            client_key, self._max_session_age_seconds
        )

        if not recent_sessions:
            return None

        for session in recent_sessions:
            stored_bundle = await self._session_repository.get_fingerprint_bundle(
                session.id
            )

            if stored_bundle and self._has_rolling_overlap(bundle, stored_bundle):
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Fuzzy match: session %s matched via rolling fingerprint overlap",
                        session.id,
                    )
                return str(session.id)

            if stored_bundle and self._has_user_hash_alignment(bundle, stored_bundle):
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Fuzzy match: session %s matched via last user hash continuity",
                        session.id,
                    )
                return str(session.id)

            if (
                stored_bundle
                and self._has_topic_similarity(bundle, stored_bundle)
                and await self._is_recent_session(session.id)
            ):
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Fuzzy match: session %s matched via topic similarity",
                        session.id,
                    )
                return str(session.id)

            # Legacy fallback using stored primary fingerprint
            session_fp = await self._session_repository.get_session_fingerprint(
                session.id
            )
            if session_fp and session_fp in bundle.rolling_fingerprints:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Fuzzy match: session %s matched via legacy rolling fingerprint",
                        session.id,
                    )
                return str(session.id)

        return None

    def _has_rolling_overlap(
        self,
        incoming: ConversationFingerprintBundle,
        stored: ConversationFingerprintBundle,
    ) -> bool:
        """Check whether rolling fingerprint windows overlap."""
        if not incoming.rolling_fingerprints or not stored.rolling_fingerprints:
            return False
        return bool(
            incoming.rolling_fingerprints.intersection(stored.rolling_fingerprints)
        )

    def _has_user_hash_alignment(
        self,
        incoming: ConversationFingerprintBundle,
        stored: ConversationFingerprintBundle,
    ) -> bool:
        """Check whether the last user message hash aligns."""
        return bool(
            incoming.last_user_hash
            and stored.last_user_hash
            and incoming.last_user_hash == stored.last_user_hash
        )

    def _has_topic_similarity(
        self,
        incoming: ConversationFingerprintBundle,
        stored: ConversationFingerprintBundle,
    ) -> bool:
        """Check whether the topic token sets are similar enough."""
        if (
            not incoming.topic_tokens
            or not stored.topic_tokens
            or self._topic_similarity_threshold <= 0
        ):
            return False

        intersection = incoming.topic_tokens.intersection(stored.topic_tokens)
        if not intersection:
            return False

        union = incoming.topic_tokens.union(stored.topic_tokens)
        if not union:
            return False

        intersection_size = len(intersection)
        union_size = len(union)
        similarity = intersection_size / union_size

        if similarity >= self._topic_similarity_threshold:
            return True

        return (
            self._topic_overlap_min_tokens > 0
            and intersection_size >= self._topic_overlap_min_tokens
            and similarity >= 0.18
        )

    async def _is_recent_session(self, session_id: str) -> bool:
        """Check whether a candidate session was active recently."""
        if self._recent_session_window_seconds <= 0:
            return True

        last_access = await self._session_repository.get_session_last_access(session_id)
        if last_access is None:
            return True

        return (time.time() - last_access) <= self._recent_session_window_seconds
