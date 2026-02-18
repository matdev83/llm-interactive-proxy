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
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from requests.adapters import HTTPAdapter  # type: ignore[import-untyped]

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
from src.core.utils.usage_recalculation import calculate_outbound_tokens

if TYPE_CHECKING:
    from src.core.services.translation_service import TranslationService


logger = logging.getLogger(__name__)

# Module-level shared connection pool for Code Assist API.
# Kept outside any class so the pool survives backend connector
# re-initialisation (which happens on every cache-miss in the
# BackendLifecycleManager).  This matches the keep-alive behaviour
# of the native gemini-cli (gaxios/Node.js default keep-alive).
_SHARED_CODE_ASSIST_ADAPTER = HTTPAdapter(pool_connections=2, pool_maxsize=8)


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

        # Reference the module-level adapter so the connection pool
        # survives connector re-initialisation across requests.
        self._shared_https_adapter = _SHARED_CODE_ASSIST_ADAPTER

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
        # Mount shared connection pool so TCP+TLS connections are reused
        # across sequential requests instead of opening a fresh socket each time.
        auth_session.mount("https://", self._shared_https_adapter)
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

        canonical_request = self._strip_reasoning_content_if_configured(
            canonical_request
        )
        canonical_request = self._truncate_tool_outputs_if_configured(canonical_request)

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
            sample_missing = self._collect_missing_tool_call_samples(
                canonical_request,
                signature_session_id=(
                    signature_session_id if strict_signature_validation else None
                ),
                strict_validation=strict_signature_validation,
            )
            logger.warning(
                "Downgrading tool calls to plain text due to missing Gemini thought signatures",
                extra={
                    "missing_signatures": missing_signatures,
                    "tool_calls_total": total_tool_calls,
                    "tool_calls_with_signatures": with_signatures,
                    "missing_tool_call_samples": sample_missing,
                    "effective_model": effective_model,
                    "session_id": session_id[:8] if session_id else "none",
                    "signature_namespace": signature_namespace or "none",
                    "strict_signature_validation": strict_signature_validation,
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

        if session_id:
            code_assist_request.setdefault("session_id", session_id)

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

        # Use IPromptLimiter interface for Code Assist request token estimation.
        code_assist_prompt_tokens_estimate = self._prompt_limiter._estimate_prompt_tokens(
            code_assist_request
        )
        # Safety net: in some tool-heavy sessions, Code Assist-part serialization can
        # undercount relative to the canonical outbound request shape.
        fallback_prompt_tokens_estimate = calculate_outbound_tokens(
            request_data,
            model=effective_model,
            label="prompt_estimation_fallback",
        )
        prompt_tokens_estimate = max(
            code_assist_prompt_tokens_estimate or 0,
            fallback_prompt_tokens_estimate or 0,
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
                f" (code_assist={code_assist_prompt_tokens_estimate}, "
                f"fallback={fallback_prompt_tokens_estimate})"
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

    def _strip_reasoning_content_if_configured(self, canonical_request: Any) -> Any:
        if not self._should_strip_reasoning_content():
            return canonical_request

        messages = getattr(canonical_request, "messages", None)
        if not isinstance(messages, list) or not messages:
            return canonical_request

        updated_messages: list[Any] = []
        stripped_count = 0
        for msg in messages:
            if isinstance(msg, dict):
                if (
                    "reasoning_content" in msg
                    or "reasoning" in msg
                    or "thinking" in msg
                    or "thought" in msg
                ):
                    updated = dict(msg)
                    updated.pop("reasoning_content", None)
                    updated.pop("reasoning", None)
                    updated.pop("thinking", None)
                    updated.pop("thought", None)
                    updated_messages.append(updated)
                    stripped_count += 1
                else:
                    updated_messages.append(msg)
                continue

            reasoning_value = getattr(msg, "reasoning_content", None)
            if reasoning_value:
                if hasattr(msg, "model_copy"):
                    msg = msg.model_copy(update={"reasoning_content": None})
                else:
                    with contextlib.suppress(Exception):
                        msg.reasoning_content = None
                stripped_count += 1
            updated_messages.append(msg)

        if stripped_count > 0:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Stripped reasoning_content from %d messages before Code Assist translation",
                    stripped_count,
                )
            return self._replace_messages(canonical_request, updated_messages)

        return canonical_request

    def _truncate_tool_outputs_if_configured(self, canonical_request: Any) -> Any:
        max_chars, max_lines = self._resolve_tool_output_truncation_limits()
        if max_chars is None and max_lines is None:
            return canonical_request

        messages = getattr(canonical_request, "messages", None)
        if not isinstance(messages, list) or not messages:
            return canonical_request

        updated_messages: list[Any] = []
        truncated_count = 0
        total_saved = 0
        for msg in messages:
            role = (
                msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
            )
            if role != "tool":
                updated_messages.append(msg)
                continue

            content = (
                msg.get("content")
                if isinstance(msg, dict)
                else getattr(msg, "content", None)
            )
            if not isinstance(content, str):
                updated_messages.append(msg)
                continue

            truncated_text, truncated, saved = self._truncate_text_content(
                content, max_chars=max_chars, max_lines=max_lines
            )
            if not truncated:
                updated_messages.append(msg)
                continue

            if isinstance(msg, dict):
                updated = dict(msg)
                updated["content"] = truncated_text
                updated_messages.append(updated)
            else:
                if hasattr(msg, "model_copy"):
                    updated_messages.append(
                        msg.model_copy(update={"content": truncated_text})
                    )
                else:
                    with contextlib.suppress(Exception):
                        msg.content = truncated_text
                    updated_messages.append(msg)

            truncated_count += 1
            total_saved += saved

        if truncated_count > 0:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Truncated %d tool outputs before Code Assist translation (saved %d chars)",
                    truncated_count,
                    total_saved,
                )
            return self._replace_messages(canonical_request, updated_messages)

        return canonical_request

    def _replace_messages(self, canonical_request: Any, messages: list[Any]) -> Any:
        if hasattr(canonical_request, "model_copy"):
            try:
                return canonical_request.model_copy(update={"messages": messages})
            except Exception:
                pass
        with contextlib.suppress(Exception):
            canonical_request.messages = messages
        return canonical_request

    def _should_strip_reasoning_content(self) -> bool:
        env_value = os.environ.get("GEMINI_STRIP_REASONING_CONTENT")
        env_bool = self._coerce_bool(env_value)
        if env_bool is not None:
            return env_bool

        extras = self._get_backend_extras()
        extra_value = extras.get("strip_reasoning_content")
        extra_bool = self._coerce_bool(extra_value)
        if extra_bool is not None:
            return extra_bool

        return True

    def _resolve_tool_output_truncation_limits(self) -> tuple[int | None, int | None]:
        if self._is_compaction_enabled():
            self._log_truncation_skip()
            return None, None

        env_chars = os.environ.get("GEMINI_TOOL_OUTPUT_TRUNCATE_CHARS")
        env_lines = os.environ.get("GEMINI_TOOL_OUTPUT_TRUNCATE_LINES")

        extras = self._get_backend_extras()

        max_chars = self._coerce_positive_int(env_chars)
        if max_chars is None:
            for key in (
                "tool_output_truncate_chars",
                "truncate_tool_output_threshold",
                "truncateToolOutputThreshold",
                "tool_output_max_chars",
            ):
                if key in extras:
                    max_chars = self._coerce_positive_int(extras.get(key))
                    if max_chars is not None:
                        break

        max_lines = self._coerce_positive_int(env_lines)
        if max_lines is None:
            for key in (
                "tool_output_truncate_lines",
                "truncate_tool_output_lines",
                "truncateToolOutputLines",
                "tool_output_max_lines",
            ):
                if key in extras:
                    max_lines = self._coerce_positive_int(extras.get(key))
                    if max_lines is not None:
                        break

        return max_chars, max_lines

    def _is_compaction_enabled(self) -> bool:
        connector = self._connector_context
        config = getattr(connector, "config", None)
        if config is None:
            return False

        compaction = getattr(config, "compaction", None)
        if isinstance(compaction, dict):
            return bool(compaction.get("enabled"))
        return bool(getattr(compaction, "enabled", False))

    def _log_truncation_skip(self) -> None:
        level = self._resolve_truncation_log_level()
        if level is None:
            return
        if logger.isEnabledFor(level):
            logger.log(
                level,
                "Skipping tool output truncation because history compaction is enabled",
            )

    def _resolve_truncation_log_level(self) -> int | None:
        env_value = os.environ.get("GEMINI_TOOL_OUTPUT_TRUNCATION_LOG_LEVEL")
        level = self._coerce_log_level(env_value)
        if level is not None or env_value is not None:
            return level

        extras = self._get_backend_extras()
        extra_value = extras.get("tool_output_truncation_log_level")
        return self._coerce_log_level(extra_value)

    @staticmethod
    def _coerce_log_level(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value if value >= 0 else None
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"off", "none", "false", "0"}:
                return None
            level = logging.getLevelName(normalized.upper())
            if isinstance(level, int):
                return level
        return None

    def _get_backend_extras(self) -> dict[str, Any]:
        connector = self._connector_context
        config = getattr(connector, "config", None)
        backend_type = getattr(connector, "backend_type", None)
        if not config or not backend_type:
            return {}

        backend_key = str(backend_type)
        extras = self._lookup_backend_extras(config, backend_key)
        if extras:
            return extras

        alt_key = self._alternate_backend_key(backend_key)
        if alt_key:
            alt_extras = self._lookup_backend_extras(config, alt_key)
            if alt_extras:
                return alt_extras
            if alt_extras is not None:
                return alt_extras

        return extras or {}

    @staticmethod
    def _lookup_backend_extras(config: Any, backend_key: str) -> dict[str, Any] | None:
        try:
            backends = config.backends
            if hasattr(backends, "lookup"):
                backend_config = backends.lookup(backend_key)
            else:
                backend_config = backends.get(backend_key)
        except Exception:
            backend_config = None
        extras = getattr(backend_config, "extra", None) if backend_config else None
        if isinstance(extras, dict):
            return extras
        return None

    @staticmethod
    def _alternate_backend_key(backend_key: str) -> str | None:
        if "-" in backend_key:
            return backend_key.replace("-", "_")
        if "_" in backend_key:
            return backend_key.replace("_", "-")
        return None

    @staticmethod
    def _coerce_bool(value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return None

    @staticmethod
    def _coerce_positive_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            coerced = int(value)
        except (TypeError, ValueError):
            return None
        if coerced <= 0:
            return None
        return coerced

    @staticmethod
    def _truncate_text_content(
        value: str, *, max_chars: int | None, max_lines: int | None
    ) -> tuple[str, bool, int]:
        if max_chars is None and max_lines is None:
            return value, False, 0

        marker = "... [CONTENT TRUNCATED] ..."
        original_len = len(value)
        text = value
        truncated = False

        if isinstance(max_lines, int) and max_lines > 0:
            lines = text.splitlines()
            if len(lines) > max_lines:
                head = max(1, max_lines // 5)
                tail = max_lines - head
                text = "\n".join(lines[:head] + [marker] + lines[-tail:])
                truncated = True

        if isinstance(max_chars, int) and max_chars > 0 and len(text) > max_chars:
            head = max(1, max_chars // 5)
            tail = max_chars - head - len(marker)
            if tail <= 0:
                text = text[:max_chars]
            else:
                text = text[:head] + marker + text[-tail:]
            truncated = True

        saved = max(original_len - len(text), 0) if truncated else 0
        return text, truncated, saved

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

    def _extract_tool_call_name(self, tc: Any) -> str | None:
        if isinstance(tc, dict):
            function = tc.get("function")
            if isinstance(function, dict):
                name = function.get("name")
            else:
                name = tc.get("name")
        else:
            function = getattr(tc, "function", None)
            name = getattr(function, "name", None) if function else None

        if isinstance(name, str) and name:
            return name
        return None

    def _collect_missing_tool_call_samples(
        self,
        canonical_request: Any,
        *,
        signature_session_id: str | None,
        strict_validation: bool,
        max_samples: int = 5,
    ) -> list[dict[str, Any]]:
        messages = getattr(canonical_request, "messages", None)
        if not isinstance(messages, list) or not messages:
            return []

        samples: list[dict[str, Any]] = []
        for idx, msg in enumerate(messages):
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
                if self._is_signature_valid(
                    tc,
                    signature_session_id=signature_session_id,
                    strict_validation=strict_validation,
                ):
                    continue
                sample = {
                    "name": self._extract_tool_call_name(tc) or "unknown",
                    "id": self._extract_tool_call_id(tc) or "unknown",
                    "message_index": idx,
                }
                samples.append(sample)
                if len(samples) >= max_samples:
                    return samples

        return samples

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
