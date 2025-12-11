"""
Chat request preparation for Gemini OAuth connectors.

This module provides shared logic for preparing Code Assist API requests,
eliminating duplication between streaming and non-streaming paths.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from src.connectors.gemini_base.credentials import _StaticTokenCreds
from src.core.common.exceptions import AuthenticationError
from src.core.security.loop_prevention import LOOP_GUARD_HEADER, LOOP_GUARD_VALUE

if TYPE_CHECKING:
    from src.connectors.gemini_base.connector import GeminiOAuthBaseConnector
    from src.core.services.translation_service import TranslationService


logger = logging.getLogger(__name__)


@runtime_checkable
class IConnectorDependencies(Protocol):
    """Narrow interface defining what ChatRequestPreparer needs from a connector.

    This protocol allows testing with mock implementations and avoids
    coupling the preparer to the full connector class.
    """

    @property
    def _oauth_credentials(self) -> dict[str, Any] | None:
        """Get current OAuth credentials."""
        ...

    @property
    def _request_counter(self) -> Any:
        """Get request counter (may be None)."""
        ...

    async def _refresh_token_if_needed(self) -> bool:
        """Ensure a valid access token is available."""
        ...

    def _get_session_headers(self) -> dict[str, str]:
        """Get headers for AuthorizedSession requests."""
        ...

    async def _discover_project_id(self, auth_session: Any) -> str:
        """Discover the project ID for Code Assist API."""
        ...

    def _convert_system_messages_for_code_assist(
        self, gemini_request: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Convert system messages for Code Assist API format."""
        ...

    def _build_code_assist_request(
        self, gemini_request: dict[str, Any], final_contents: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Build Code Assist API request from Gemini format."""
        ...

    def _sanitize_code_assist_tools(
        self, canonical_request: Any, code_assist_request: dict[str, Any]
    ) -> None:
        """Sanitize tool definitions for Code Assist API."""
        ...

    def _estimate_prompt_tokens(
        self, code_assist_request: dict[str, Any]
    ) -> int | None:
        """Estimate the number of prompt tokens in the request."""
        ...

    def _enforce_prompt_limit(
        self,
        prompt_tokens: int | None,
        effective_model: str,
        *,
        request_id: str | None = None,
    ) -> None:
        """Enforce prompt token limits, raising InvalidRequestError if exceeded."""
        ...

    def _build_code_assist_request_body(
        self,
        effective_model: str,
        project_id: str,
        request_data: Any,
        code_assist_request: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the final request body for the Code Assist API."""
        ...

    def _inject_thought_signatures(
        self, canonical_request: Any, session_id: str
    ) -> None:
        """Inject stored thought_signatures into tool_calls."""
        ...

    def _log_tool_call_signature_state(
        self, canonical_request: Any, session_id: str, effective_model: str
    ) -> None:
        """Log presence/absence of thought signatures."""
        ...


@dataclass
class PreparedChatRequest:
    """Result of preparing a chat request for Code Assist API."""

    auth_session: Any
    """Authorized session for making API requests."""

    project_id: str
    """Project ID for Code Assist API."""

    canonical_request: Any
    """The canonical request object."""

    code_assist_request: dict[str, Any]
    """The prepared Code Assist request body."""

    prompt_tokens_estimate: int | None
    """Estimated prompt token count."""

    effective_model: str
    """The effective model name to use."""

    session_id: str
    """Session ID for thought signature caching."""

    build_request_body: Callable[[], dict[str, Any]]
    """Function to build the final request body."""


class ChatRequestPreparer:
    """Prepares chat requests for the Code Assist API.

    This class encapsulates the common setup logic shared between
    streaming and non-streaming chat completion paths.

    The preparer can work with any object that implements IConnectorDependencies,
    allowing for testing with mock implementations.
    """

    def __init__(
        self,
        connector: "GeminiOAuthBaseConnector | IConnectorDependencies",
        translation_service: "TranslationService",
        *,
        google_auth_provider: GoogleAuthProvider | None = None,
        thought_signature_service: ThoughtSignatureService | None = None,
        token_estimator: TiktokenEstimator | None = None,
    ) -> None:
        """Initialize the preparer.

        Args:
            connector: The connector instance providing credentials and config.
                      Can be any object implementing IConnectorDependencies.
            translation_service: Service for request/response translation.
            google_auth_provider: Optional Google auth provider for testing.
            thought_signature_service: Optional thought signature service for testing.
            token_estimator: Optional token estimator for testing.
        """
        self._connector = connector
        self._translation_service = translation_service
        self._google_auth_provider = google_auth_provider
        self._thought_signature_service = thought_signature_service
        self._token_estimator = token_estimator

    async def prepare(
        self,
        request_data: Any,
        effective_model: str,
        *,
        is_streaming: bool = False,
    ) -> PreparedChatRequest:
        """Prepare a chat request for the Code Assist API.

        This method handles all common setup steps:
        - Token refresh
        - Request counter increment
        - Auth session creation
        - Project ID discovery
        - Request translation and building
        - Tool sanitization
        - Prompt limit enforcement

        Args:
            request_data: The canonical chat request.
            effective_model: The model name to use.
            is_streaming: Whether this is for a streaming request.

        Returns:
            PreparedChatRequest with all necessary data for the API call.

        Raises:
            AuthenticationError: If credentials are invalid or refresh fails.
        """
        connector = self._connector
        log_prefix = "[STREAMING] " if is_streaming else ""

        # Ensure token is refreshed before making the API call
        if not await connector._refresh_token_if_needed():
            raise AuthenticationError(
                f"Failed to refresh OAuth token for {'streaming ' if is_streaming else ''}API call"
            )

        if connector._request_counter:
            connector._request_counter.increment()

        # Create an authorized session using the access token directly
        if not connector._oauth_credentials:
            raise AuthenticationError(
                f"No OAuth credentials available for {'streaming ' if is_streaming else ''}API call"
            )

        access_token = connector._oauth_credentials.get("access_token")
        if not access_token:
            raise AuthenticationError("Missing access_token in OAuth credentials")

        google_auth = self._google_auth_provider or get_default_google_auth_provider()
        auth_session = google_auth.create_authorized_session(
            _StaticTokenCreds(access_token)
        )
        auth_session.headers.setdefault(LOOP_GUARD_HEADER, LOOP_GUARD_VALUE)
        # Apply custom headers (e.g., User-Agent for Antigravity)
        for key, value in connector._get_session_headers().items():
            auth_session.headers[key] = value

        # Discover project ID (required for Code Assist API)
        project_id = await connector._discover_project_id(auth_session)

        canonical_request = request_data

        # Debug logging to trace message flow
        if logger.isEnabledFor(logging.DEBUG):
            message_count = (
                len(canonical_request.messages)
                if hasattr(canonical_request, "messages")
                else 0
            )
            logger.debug(
                f"{log_prefix}Processing {message_count} messages for Gemini Code Assist API"
            )
            if message_count > 0 and hasattr(canonical_request, "messages"):
                last_msg = canonical_request.messages[-1]
                logger.debug(
                    f"{log_prefix}Last message role={getattr(last_msg, 'role', 'unknown')}, "
                    f"content length={len(str(getattr(last_msg, 'content', '')))}"
                )

        # Inject stored thought_signatures for clients that don't preserve extra_content
        session_id = getattr(request_data, "session_id", None) or ""
        # Only inject cached signatures when we have a real session identifier.
        # Using an empty key risks cross-session leakage and "corrupted thought signature" errors.
        # This applies to both streaming and non-streaming paths for consistency.
        if session_id:
            connector._inject_thought_signatures(canonical_request, session_id)
        connector._log_tool_call_signature_state(
            canonical_request, session_id, effective_model
        )

        # Convert from canonical/domain format to Gemini API format
        gemini_request = self._translation_service.from_domain_to_gemini_request(
            canonical_request
        )

        # Use mixin method to convert system messages (KiloCode's approach)
        # This avoids the 64K token limit on the separate systemInstruction field
        final_contents = connector._convert_system_messages_for_code_assist(
            gemini_request
        )

        # Use mixin method to build Code Assist API request
        code_assist_request = connector._build_code_assist_request(
            gemini_request, final_contents
        )

        # Strip/repair unsupported tool definitions (e.g., custom tools from clients)
        # Use connector method to allow subclass overrides (extension point)
        connector._sanitize_code_assist_tools(canonical_request, code_assist_request)

        prompt_tokens_estimate = connector._estimate_prompt_tokens(code_assist_request)
        connector._enforce_prompt_limit(
            prompt_tokens_estimate,
            effective_model,
            request_id=getattr(request_data, "id", None),
        )

        # Create request body builder closure
        def build_request_body() -> dict[str, Any]:
            return connector._build_code_assist_request_body(
                effective_model=effective_model,
                project_id=project_id,
                request_data=request_data,
                code_assist_request=code_assist_request,
            )

        # Log request details for debugging token issues
        if logger.isEnabledFor(logging.DEBUG):
            first_msg_size = 0
            contents_list = code_assist_request.get("contents", [])
            if contents_list and len(contents_list) > 0:
                first_msg_parts = contents_list[0].get("parts", [])
                for part in first_msg_parts:
                    if "text" in part:
                        first_msg_size += len(part["text"])
            logger.debug(
                f"Code Assist request: first message size={first_msg_size} chars, "
                f"contents count={len(contents_list)}, "
                f"estimated tokens={prompt_tokens_estimate}"
            )

        return PreparedChatRequest(
            auth_session=auth_session,
            project_id=project_id,
            canonical_request=canonical_request,
            code_assist_request=code_assist_request,
            prompt_tokens_estimate=prompt_tokens_estimate,
            effective_model=effective_model,
            session_id=session_id,
            build_request_body=build_request_body,
        )


__all__ = [
    "ChatRequestPreparer",
    "PreparedChatRequest",
]
