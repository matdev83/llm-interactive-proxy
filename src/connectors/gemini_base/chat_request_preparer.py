"""\
Chat request preparation for Gemini OAuth connectors.

This module provides shared logic for preparing Code Assist API requests,
eliminating duplication between streaming and non-streaming paths.

Uses narrow interfaces (from connector_context.py) for dependency inversion,
enabling testing with mock implementations and avoiding coupling to concrete
connector classes.
"""

# pyright: reportPrivateUsage=false, reportPrivateImportUsage=false

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.connectors.gemini_base.connector_context import (
    IConnectorContext,
    IMessageConverter,
    IPromptLimiter,
    IRequestBodyBuilder,
    IRequestCounter,
    IThoughtSignatureService,
)
from src.connectors.gemini_base.credentials import _StaticTokenCreds
from src.connectors.gemini_base.google_auth_adapter import (
    IGoogleAuthProvider,
    get_default_google_auth_provider,
)
from src.connectors.gemini_base.thought_signature_service import (
    get_default_thought_signature_service,
)
from src.core.common.exceptions import AuthenticationError
from src.core.domain.chat_history_utils import stringify_tool_calls_and_results
from src.core.security.loop_prevention import LOOP_GUARD_HEADER, LOOP_GUARD_VALUE

if TYPE_CHECKING:
    from src.core.services.translation_service import TranslationService


logger = logging.getLogger(__name__)


@dataclass
class PreparedChatRequest:
    """Result of preparing a chat request for Code Assist API.

    This dataclass serves as the shared data boundary between request preparation
    and execution phases. It encapsulates all data needed for Code Assist API requests.

    **Data Flow**: This model flows:
    - Produced by `ChatRequestPreparer` during request preparation
    - Consumed by `ICodeAssistOrchestrator.run_streaming()` and `.run_non_streaming()`
    - Contains all necessary context for API execution (auth, project, model, etc.)

    **Service Boundaries**: Provides a clear boundary between request preparation
    (translation, validation, formatting) and execution (streaming, accumulation).
    """

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
    """Session ID for response metadata."""

    signature_session_id: str
    """Session ID scoped for thought signature caching."""

    build_request_body: Callable[[], dict[str, Any]]
    """Function to build the final request body."""


class ChatRequestPreparer:
    """Prepares chat requests for the Code Assist API.

    This class encapsulates the common setup logic shared between
    streaming and non-streaming chat completion paths.

    Uses narrow interfaces (from connector_context.py) for SOLID compliance:
    - IConnectorContext: auth credentials and project discovery
    - IMessageConverter: message conversion to Code Assist format
    - IPromptLimiter: prompt token estimation and limit enforcement
    - IRequestBodyBuilder: building final request bodies
    - IThoughtSignatureService: thought signature management
    - IRequestCounter: optional request counting

    This approach enables testing with mock implementations and avoids
    coupling to any specific connector implementation.
    """

    def __init__(
        self,
        *,
        # Narrow interfaces (preferred approach)
        connector_context: IConnectorContext | None = None,
        message_converter: IMessageConverter | None = None,
        prompt_limiter: IPromptLimiter | None = None,
        request_body_builder: IRequestBodyBuilder | None = None,
        request_counter: IRequestCounter | None = None,
        thought_signature_service: IThoughtSignatureService | None = None,
        # Injectable services
        translation_service: "TranslationService | None" = None,
        google_auth_provider: IGoogleAuthProvider | None = None,
        # Backward compatibility: accepts a connector that provides all interfaces
        connector: Any | None = None,
    ) -> None:
        """Initialize the preparer.

        Args:
            connector_context: Interface for auth credentials and project discovery.
            message_converter: Interface for message conversion.
            prompt_limiter: Interface for prompt limit enforcement.
            request_body_builder: Interface for building request bodies.
            request_counter: Optional interface for request counting.
            thought_signature_service: Interface for thought signature management.
            translation_service: Service for request/response translation.
            google_auth_provider: Google auth provider for creating sessions.
            connector: (Backward compat) A connector implementing all interfaces.
        """
        # If a connector is provided, extract interfaces from it
        # This maintains backward compatibility while enabling DI
        if connector is not None:
            self._connector_context: IConnectorContext = connector
            self._message_converter: IMessageConverter = connector
            self._prompt_limiter: IPromptLimiter = connector
            self._request_body_builder: IRequestBodyBuilder = connector
            self._request_counter: IRequestCounter | None = getattr(
                connector, "_request_counter", None
            )
        else:
            if connector_context is None:
                raise ValueError("connector_context or connector must be provided")
            self._connector_context = connector_context
            self._message_converter = message_converter  # type: ignore[assignment]
            self._prompt_limiter = prompt_limiter  # type: ignore[assignment]
            self._request_body_builder = request_body_builder  # type: ignore[assignment]
            self._request_counter = request_counter

        self._translation_service = translation_service
        self._google_auth_provider = (
            google_auth_provider or get_default_google_auth_provider()
        )
        self._thought_signature_service = (
            thought_signature_service or get_default_thought_signature_service()
        )

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
        log_prefix = "[STREAMING] " if is_streaming else ""

        session_id = getattr(request_data, "session_id", None) or ""

        # Ensure token is refreshed before making the API call
        # Uses IConnectorContext interface
        if not await self._connector_context._refresh_token_if_needed(
            session_id=session_id
        ):
            raise AuthenticationError(
                f"Failed to refresh OAuth token for {'streaming ' if is_streaming else ''}API call"
            )

        # Increment request counter if available (offload to thread to avoid blocking)
        if self._request_counter:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._request_counter.increment)

        # Create an authorized session using the access token directly
        # Uses IConnectorContext interface
        if not self._connector_context._oauth_credentials:
            raise AuthenticationError(
                f"No OAuth credentials available for {'streaming ' if is_streaming else ''}API call"
            )

        access_token = self._connector_context._oauth_credentials.get("access_token")
        if not access_token:
            raise AuthenticationError("Missing access_token in OAuth credentials")

        auth_session = self._google_auth_provider.create_authorized_session(
            _StaticTokenCreds(access_token)
        )
        auth_session.headers.setdefault(LOOP_GUARD_HEADER, LOOP_GUARD_VALUE)

        # Apply custom headers (e.g., User-Agent for Antigravity)
        # Uses IConnectorContext interface
        for key, value in self._connector_context._get_session_headers().items():
            auth_session.headers[key] = value

        # Discover project ID (required for Code Assist API)
        # Uses IConnectorContext interface
        project_id = await self._connector_context._discover_project_id(auth_session)

        canonical_request = request_data

        # Backward compatibility: normalize dict-based messages to domain ChatMessage.
        # The Gemini domain translator expects messages to have `.role` / `.content`.
        try:
            from src.core.domain.chat import ChatMessage

            raw_messages = getattr(canonical_request, "messages", None)
            if (
                isinstance(raw_messages, list)
                and raw_messages
                and any(isinstance(m, dict) for m in raw_messages)
            ):
                normalized: list[ChatMessage] = []
                for m in raw_messages:
                    if isinstance(m, ChatMessage):
                        normalized.append(m)
                    elif isinstance(m, dict):
                        normalized.append(
                            ChatMessage(
                                role=str(m.get("role", "user")),
                                content=str(m.get("content", "")),
                            )
                        )
                    else:
                        normalized.append(
                            ChatMessage(
                                role=str(getattr(m, "role", "user")),
                                content=str(getattr(m, "content", "")),
                            )
                        )
                canonical_request.messages = normalized

                # Backward compatibility: some legacy callers/tests set `tools` to a plain
                # Mock (truthy but not iterable). The domain translator expects `tools`
                # to be a list or None.
                tools_val = getattr(canonical_request, "tools", None)
                if tools_val is not None and not isinstance(tools_val, list):
                    canonical_request.tools = None

                # Backward compatibility: tests may provide a Mock request object where
                # optional numeric fields default to `Mock()` (truthy but non-numeric).
                # The domain translator expects these to be numbers or None.
                numeric_fields: dict[str, type] = {
                    "n": int,
                    "top_k": int,
                    "max_tokens": int,
                    "max_completion_tokens": int,
                    "temperature": float,
                    "top_p": float,
                }
                for field, expected_type in numeric_fields.items():
                    val = getattr(canonical_request, field, None)
                    if val is None:
                        continue
                    if not isinstance(val, expected_type):
                        setattr(canonical_request, field, None)
        except Exception as e:
            # Log failure but proceed with best-effort normalization
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"{log_prefix}Backward compatibility normalization failed: {e}",
                    exc_info=True,
                )

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
        # Uses IThoughtSignatureService interface
        signature_namespace = self._resolve_thought_signature_namespace()
        signature_session_id = self._compose_signature_session_id(
            session_id, signature_namespace
        )
        strict_signature_validation = bool(signature_namespace and session_id)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Thought signature namespace resolved: %s (session=%s)",
                signature_namespace or "none",
                session_id[:8] if session_id else "none",
            )

        # Only inject cached signatures when we have a real session identifier.
        # Using an empty key risks cross-session leakage and "corrupted thought signature" errors.
        if session_id:
            self._thought_signature_service.inject_signatures(
                canonical_request, signature_session_id
            )
        self._thought_signature_service.log_signature_state(
            canonical_request, session_id, effective_model
        )

        # If the prompt contains tool calls without thought signatures, Vertex will reject
        # the request (400 INVALID_ARGUMENT). This commonly happens when a client switches
        # from a non-Gemini backend mid-session: those tool_calls cannot have valid
        # Google thought signatures.
        #
        # Best-effort mitigation: downgrade such tool calls to plain text transcript and
        # convert `role=tool` messages into normal user text, so the session can continue.
        missing_signatures = self._count_tool_calls_missing_thought_signature(
            canonical_request,
            signature_session_id if strict_signature_validation else None,
            strict_signature_validation,
        )
        if missing_signatures:
            total_tool_calls = self._count_tool_calls(canonical_request)
            with_signatures = self._count_tool_calls_with_thought_signature(
                canonical_request
            )
            logger.warning(
                "Downgrading tool calls to plain text due to missing Gemini thought signatures",
                extra={
                    "missing_signatures": missing_signatures,
                    "tool_calls_total": total_tool_calls,
                    "tool_calls_with_signatures": with_signatures,
                    "effective_model": effective_model,
                    "session_id": session_id[:8] if session_id else "none",
                    "signature_namespace": signature_namespace or "none",
                },
            )
            canonical_request = self._downgrade_tool_calls_to_text(
                canonical_request,
                signature_session_id if strict_signature_validation else None,
                strict_signature_validation,
            )

        # Convert from canonical/domain format to Gemini API format
        if self._translation_service is None:
            raise ValueError("translation_service is required")
        gemini_request = self._translation_service.from_domain_to_gemini_request(
            canonical_request
        )

        # Use IMessageConverter interface to convert system messages
        # This avoids the 64K token limit on the separate systemInstruction field
        final_contents = (
            self._message_converter._convert_system_messages_for_code_assist(
                gemini_request
            )
        )

        # Use IMessageConverter interface to build Code Assist API request
        code_assist_request = self._message_converter._build_code_assist_request(
            gemini_request, final_contents
        )

        # Strip/repair unsupported tool definitions (e.g., custom tools from clients)
        # Uses IMessageConverter interface
        self._message_converter._sanitize_code_assist_tools(
            canonical_request, code_assist_request
        )

        # Remove empty/None 'tools' and 'toolConfig' from code_assist_request
        # This ensures the API request body does not contain empty fields
        # that might cause validation errors or unexpected behavior.
        if "tools" in code_assist_request:
            tools_val = code_assist_request["tools"]
            if not tools_val:  # Handles None, [], {}
                del code_assist_request["tools"]

        if "toolConfig" in code_assist_request:
            tool_config_val = code_assist_request["toolConfig"]
            if not tool_config_val:  # Handles None, [], {}
                del code_assist_request["toolConfig"]

        # Use IPromptLimiter interface for token estimation and limit enforcement
        prompt_tokens_estimate = self._prompt_limiter._estimate_prompt_tokens(
            code_assist_request
        )
        self._prompt_limiter._enforce_prompt_limit(
            prompt_tokens_estimate,
            effective_model,
            request_id=getattr(request_data, "id", None),
        )

        # Create request body builder closure using IRequestBodyBuilder interface
        def build_request_body() -> dict[str, Any]:
            # Final safety check: ensure no empty tools/toolConfig
            if not code_assist_request.get("tools"):
                code_assist_request.pop("tools", None)
                code_assist_request.pop("toolConfig", None)

            return self._request_body_builder._build_code_assist_request_body(
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
            signature_session_id=signature_session_id,
            build_request_body=build_request_body,
        )

    def _resolve_thought_signature_namespace(self) -> str | None:
        connector_context = self._connector_context

        getter = getattr(connector_context, "get_thought_signature_namespace", None)
        if callable(getter):
            try:
                namespace = getter()
            except Exception:
                namespace = None
            if isinstance(namespace, str) and namespace.strip():
                return namespace.strip()

        namespace = getattr(connector_context, "thought_signature_namespace", None)
        if isinstance(namespace, str) and namespace.strip():
            return namespace.strip()

        return None

    def _compose_signature_session_id(
        self, session_id: str, signature_namespace: str | None
    ) -> str:
        if session_id and signature_namespace:
            return f"{session_id}|{signature_namespace}"
        return session_id

    def _has_tool_calls_missing_thought_signature(self, canonical_request: Any) -> bool:
        return self._count_tool_calls_missing_thought_signature(canonical_request) > 0

    def _count_tool_calls(self, canonical_request: Any) -> int:
        messages = getattr(canonical_request, "messages", None)
        if not isinstance(messages, list) or not messages:
            return 0

        total = 0
        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get("role")
                tool_calls = msg.get("tool_calls")
            else:
                role = getattr(msg, "role", None)
                tool_calls = getattr(msg, "tool_calls", None)

            if role != "assistant" or not tool_calls:
                continue
            if not isinstance(tool_calls, list):
                continue
            total += len(tool_calls)

        return total

    def _count_tool_calls_with_thought_signature(self, canonical_request: Any) -> int:
        messages = getattr(canonical_request, "messages", None)
        if not isinstance(messages, list) or not messages:
            return 0

        total = 0
        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get("role")
                tool_calls = msg.get("tool_calls")
            else:
                role = getattr(msg, "role", None)
                tool_calls = getattr(msg, "tool_calls", None)

            if role != "assistant" or not tool_calls:
                continue
            if not isinstance(tool_calls, list):
                continue

            for tc in tool_calls:
                if self._extract_thought_signature(tc):
                    total += 1

        return total

    def _count_tool_calls_missing_thought_signature(
        self,
        canonical_request: Any,
        signature_session_id: str | None = None,
        strict_validation: bool = False,
    ) -> int:
        messages = getattr(canonical_request, "messages", None)
        if not isinstance(messages, list) or not messages:
            return 0

        missing = 0
        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get("role")
                tool_calls = msg.get("tool_calls")
            else:
                role = getattr(msg, "role", None)
                tool_calls = getattr(msg, "tool_calls", None)

            if role != "assistant" or not tool_calls:
                continue
            if not isinstance(tool_calls, list):
                continue

            for tc in tool_calls:
                if not self._is_signature_valid(
                    tc,
                    signature_session_id=signature_session_id,
                    strict_validation=strict_validation,
                ):
                    missing += 1

        return missing

    def _extract_tool_call_id(self, tc: Any) -> str | None:
        if isinstance(tc, dict):
            tc_id = tc.get("id")
        else:
            tc_id = getattr(tc, "id", None)

        if isinstance(tc_id, str) and tc_id:
            return tc_id
        return None

    def _extract_thought_signature(self, tc: Any) -> str | None:
        extra_content: Any | None = None
        if isinstance(tc, dict):
            extra_content = tc.get("extra_content")
        else:
            extra_content = getattr(tc, "extra_content", None)

        if not isinstance(extra_content, dict):
            return None

        google_extra = extra_content.get("google")
        if isinstance(google_extra, dict):
            sig = google_extra.get("thought_signature")
            if isinstance(sig, str) and sig:
                return sig

        # Some older paths may store the signature at the top-level extra_content.
        sig2 = extra_content.get("thought_signature")
        if isinstance(sig2, str) and sig2:
            return sig2

        return None

    def _is_signature_valid(
        self,
        tc: Any,
        *,
        signature_session_id: str | None,
        strict_validation: bool,
    ) -> bool:
        sig = self._extract_thought_signature(tc)
        if not sig:
            return False

        if not strict_validation or not signature_session_id:
            return True

        tc_id = self._extract_tool_call_id(tc)
        if not tc_id:
            return False

        cached_sig = self._thought_signature_service.get_cached_signature(
            signature_session_id,
            tc_id,
        )
        if not cached_sig:
            return False

        return cached_sig == sig

    def _downgrade_tool_calls_to_text(
        self,
        canonical_request: Any,
        signature_session_id: str | None = None,
        strict_validation: bool = False,
    ) -> Any:
        """Downgrade tool calls/results to plain text for signature-required backends.

        Vertex Code Assist requires thought signatures on functionCall parts.
        When we don't have them (e.g., backend switch from a non-Gemini model),
        we convert tool calls/results into regular text so the request is still valid.
        """

        messages = getattr(canonical_request, "messages", None)
        if not isinstance(messages, list) or not messages:
            return canonical_request

        signature_checker: Callable[[Any], bool]
        if strict_validation:
            signature_checker = lambda tc: self._is_signature_valid(
                tc,
                signature_session_id=signature_session_id,
                strict_validation=True,
            )
        else:
            signature_checker = lambda tc: bool(self._extract_thought_signature(tc))

        downgraded = stringify_tool_calls_and_results(
            list(messages),
            signature_checker=signature_checker,
            include_descriptions=False,
        )

        # CanonicalChatRequest is typically frozen (ValueObject). Prefer model_copy.
        if hasattr(canonical_request, "model_copy"):
            try:
                return canonical_request.model_copy(update={"messages": downgraded})
            except Exception:
                # Fall back to best-effort attribute assignment for legacy callers/tests.
                pass

        with contextlib.suppress(Exception):
            canonical_request.messages = downgraded
        return canonical_request


__all__ = [
    "ChatRequestPreparer",
    "PreparedChatRequest",
]
