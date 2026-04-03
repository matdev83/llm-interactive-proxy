"""Response executor for OpenAI Codex connector.

This module implements the ResponseExecutor service that handles:
- Non-streaming execution with response parsing, usage metadata, and capture data
- Streaming execution with authentication retry and error mapping
- Credential refresh integration for streaming retries
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any, cast

import httpx
from fastapi import HTTPException

from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.connectors.openai_codex.contracts import (
    CodexPayload,
    CodexRequestContext,
    CompatibilityState,
    ProviderStreamChunk,
)
from src.connectors.openai_codex.interfaces import (
    ICodexTransport,
    ICompatibilityLayer,
    ICredentialManager,
    IResponseExecutor,
)
from src.connectors.openai_codex.utils import build_codex_user_agent
from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.common.exceptions import AuthenticationError, ServiceUnavailableError
from src.core.domain.responses import (
    ResponseEnvelope,
    StreamingResponseEnvelope,
    StreamingResponseHandle,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.security.loop_prevention import ensure_loop_guard_header
from src.core.services.tool_text_renderer import OverrideRenderer

if TYPE_CHECKING:
    from src.connectors.openai import OpenAIConnector


class _CodexTransportAdapter:
    """Adapter that wraps OpenAIConnector to implement ICodexTransport protocol.

    Supports both HTTP/SSE and WebSocket transport modes based on connector configuration.
    """

    def __init__(self, connector: OpenAIConnector, use_websocket: bool = False) -> None:
        self._connector = connector
        self._use_websocket = use_websocket
        self._websocket_client: Any = None  # OpenAIWebSocketClient | None

    async def initiate_streaming_request(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        session_id: str,
    ) -> StreamingResponseHandle:
        # Opportunistically use WebSocket if enabled
        if self._use_websocket:
            return await self._initiate_websocket_streaming(
                url, payload, headers, session_id
            )

        # Default to HTTP/SSE
        return await self._connector._handle_streaming_response(  # type: ignore[misc]
            url, payload, headers, session_id, "responses"
        )

    async def _initiate_websocket_streaming(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        session_id: str,
    ) -> StreamingResponseHandle:
        """Initiate WebSocket streaming request for Codex.

        Args:
            url: Codex API endpoint URL (HTTP)
            payload: Request payload
            headers: Request headers
            session_id: Session identifier

        Returns:
            StreamingResponseHandle with WebSocket stream
        """
        # Convert HTTP URL to WebSocket URL
        ws_url = url.replace("https://", "wss://").replace("http://", "ws://")

        # Extract API key from headers
        auth_header = headers.get("Authorization", "")
        api_key = auth_header.replace("Bearer ", "") if auth_header else None
        if not api_key:
            raise AuthenticationError(message="No API key in authorization header")

        # Initialize WebSocket client if needed
        if self._websocket_client is None:
            from src.connectors.openai_websocket_client import OpenAIWebSocketClient

            # Extract base URL (everything except /responses)
            if "/responses" in ws_url:
                ws_base = ws_url.rsplit("/responses", 1)[0]
            else:
                ws_base = ws_url.rsplit("/", 1)[0]

            self._websocket_client = OpenAIWebSocketClient(
                api_key=api_key,
                api_base=ws_base,
            )

        # Create async generator for streaming
        async def _websocket_stream() -> AsyncIterator[ProcessedResponse]:
            try:
                async for response_chunk in self._websocket_client.send_response_create(
                    payload=payload,
                    previous_response_id=payload.get("previous_response_id"),
                ):
                    # Pass through ProcessedResponse from WebSocket client
                    yield response_chunk
            except Exception as e:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        "Error in Codex WebSocket stream: %s",
                        e,
                        exc_info=True,
                    )
                raise

        # Create cancel callback
        async def _cancel_callback() -> None:
            if self._websocket_client:
                await self._websocket_client.disconnect()

        return StreamingResponseHandle(
            iterator=_websocket_stream(),
            headers=headers,
            cancel_callback=_cancel_callback,
        )

    async def cleanup(self) -> None:
        """Clean up WebSocket connections."""
        if self._websocket_client is not None:
            try:
                await self._websocket_client.disconnect()
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Error disconnecting Codex WebSocket client: %s",
                        e,
                        exc_info=True,
                    )
            finally:
                self._websocket_client = None


logger = logging.getLogger(__name__)


class ResponseExecutor(IResponseExecutor):
    """Service for executing Codex API requests with retry and compatibility handling.

    This service handles:
    - Non-streaming execution with response parsing, usage metadata, and capture data
    - Streaming execution with authentication retry and error mapping
    - Credential refresh integration for streaming retries
    """

    def __init__(
        self,
        base_connector: OpenAIConnector,
        credential_manager: ICredentialManager,
        max_retries: int = 2,
        retry_backoff_seconds: tuple[float, ...] = (0.5, 1.5, 3.0),
        codex_url: str = "https://chatgpt.com/backend-api/codex/responses",
        compatibility_layer: ICompatibilityLayer | None = None,
        transport: ICodexTransport | None = None,
        use_websocket: bool = False,
    ) -> None:
        """Initialize the response executor.

        Args:
            base_connector: Base OpenAI connector for HTTP operations
            credential_manager: Credential manager for token refresh
            max_retries: Maximum retry attempts for streaming auth failures
            retry_backoff_seconds: Backoff sequence for retries
            codex_url: Codex API endpoint URL
            compatibility_layer: Optional compatibility layer for stream chunk translation
            transport: Optional transport interface for streaming HTTP requests
            use_websocket: Whether to use WebSocket transport (default: False)
        """
        self._base_connector = base_connector
        self._credential_manager = credential_manager
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._codex_url = codex_url
        self._compatibility_layer = compatibility_layer
        self._use_websocket = use_websocket
        self._max_incompatible_tool_retries = 2
        self._transport = (
            transport
            if transport is not None
            else _CodexTransportAdapter(base_connector, use_websocket=use_websocket)
        )

    async def execute(
        self, payload: CodexPayload, context: CodexRequestContext
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute Codex request with retry and compatibility handling.

        Args:
            payload: Codex API payload
            context: Request context

        Returns:
            Response envelope (streaming or non-streaming)
        """
        # Resolve renderer key from capabilities
        renderer_key = self._select_renderer_key(context.capabilities)

        if payload.stream:
            return await self._execute_streaming(payload, context, renderer_key)
        else:
            return await self._execute_non_streaming(payload, context, renderer_key)

    async def _execute_non_streaming(
        self, payload: CodexPayload, context: CodexRequestContext, renderer_key: str
    ) -> ResponseEnvelope:
        """Execute non-streaming Codex request with response parsing.

        Args:
            payload: Codex API payload
            context: Request context
            renderer_key: Renderer key for tool text rendering

        Returns:
            Response envelope with parsed response, usage metadata, and capture data
        """
        url = self._codex_url
        # Derive conversation_id from prompt_cache_key, fallback to session_id
        conversation_id = payload.prompt_cache_key or context.session_id
        headers = self._build_headers(conversation_id, context.session_id)
        payload_dict = payload.model_dump(exclude_none=True)

        # Get compatibility state from context metadata if available
        # State should always be provided by the facade via CodexRequestContext.metadata
        # when compatibility layer is enabled and successfully applied (see design.md).
        compatibility_state: CompatibilityState | None = None
        if context.metadata and "compatibility_state" in context.metadata:
            state_value = context.metadata["compatibility_state"]
            if isinstance(state_value, CompatibilityState):
                compatibility_state = state_value

        if not headers or not headers.get("Authorization"):
            raise AuthenticationError(message="No auth credentials found")

        guarded_headers = ensure_loop_guard_header(headers)

        # Retry logic for non-streaming requests with auth failures
        attempts_used = 0
        max_retries = max(0, self._max_retries)
        incompatible_tool_retries = 0

        response_json: dict[str, Any] | None = None
        response: httpx.Response | None = None

        try:
            while True:
                try:
                    response = await self._base_connector.client.post(
                        url, json=payload_dict, headers=guarded_headers
                    )
                    self._base_connector.update_quota_headers(response.headers)
                except httpx.RequestError as e:
                    logger.error(
                        "Request failed to %s. Error: %s",
                        url,
                        e,
                        exc_info=True,
                        extra={
                            "backend": "openai-codex",
                            "session_id": context.session_id,
                            "model": context.effective_model,
                        },
                    )
                    raise ServiceUnavailableError(
                        message=f"Could not connect to backend ({e})"
                    ) from e
                except httpx.HTTPStatusError as e:
                    # Handle HTTP status errors (e.g., 429, 500, etc.)
                    try:
                        err = e.response.json()
                        # Map "Instructions are not valid" errors to actionable messages
                        if (
                            e.response.status_code == 400
                            and isinstance(err, dict)
                            and err.get("detail") == "Instructions are not valid"
                        ):
                            err = {
                                "error": "codex_instructions_invalid",
                                "message": (
                                    "Codex backend rejected the instructions field as invalid. "
                                    "This usually happens when custom prompt modifications are incompatible with Codex's validation rules."
                                ),
                                "detail": err.get("detail"),
                                "suggestion": (
                                    "Set prompt_mode to 'codex_default' in your request capabilities "
                                    "(or in config via backends.openai_codex.extra.codex.default_capabilities) "
                                    "to use Codex's default instructions. System prompts are automatically "
                                    "converted to <user_instructions> blocks and do not need to be in the instructions field."
                                ),
                                "original_error": err,
                            }
                    except Exception as json_err:
                        if logger.isEnabledFor(TRACE_LEVEL):
                            logger.log(
                                TRACE_LEVEL,
                                "Failed to parse error response JSON, falling back to text: %s",
                                json_err,
                                exc_info=True,
                                extra={
                                    "backend": "openai-codex",
                                    "session_id": context.session_id,
                                    "model": context.effective_model,
                                    "status_code": e.response.status_code,
                                },
                            )
                        err = e.response.text
                    raise HTTPException(
                        status_code=e.response.status_code, detail=err
                    ) from e

                if int(response.status_code) >= 400:
                    # Check for 401 auth errors and retry if within limit
                    if response.status_code == 401 and attempts_used < max_retries:
                        # Use connector's refresh method to ensure consistency and test compatibility
                        refresh_method = getattr(
                            self._base_connector, "_refresh_access_token", None
                        )
                        if (
                            refresh_method
                            and callable(refresh_method)
                            and inspect.iscoroutinefunction(refresh_method)
                        ):
                            refreshed = await refresh_method()
                        else:
                            refreshed = (
                                await self._credential_manager.refresh_access_token()
                            )
                            # Update connector's api_key so get_headers() returns the new token
                            new_token = self._credential_manager.get_access_token()
                            if new_token and hasattr(self._base_connector, "api_key"):
                                self._base_connector.api_key = new_token
                        if not refreshed:
                            # Notify connector of authentication failure for degradation
                            degrade_method = getattr(
                                self._base_connector, "_degrade", None
                            )
                            if degrade_method is not None:
                                degrade_method(
                                    [
                                        f"Codex non-streaming token refresh failed after {attempts_used} attempts"
                                    ]
                                )
                            raise HTTPException(
                                status_code=401,
                                detail={
                                    "error": "openai_codex_auth_failed",
                                    "message": "Codex request failed authentication and could not be recovered.",
                                    "details": {
                                        "backend": "openai-codex",
                                        "attempts": attempts_used,
                                        "max_retries": max_retries,
                                    },
                                },
                            )
                        # Update headers with new token
                        fresh_headers = self._base_connector.get_headers() or {}
                        guarded_headers = ensure_loop_guard_header(fresh_headers)
                        guarded_headers["conversation_id"] = conversation_id
                        guarded_headers["session_id"] = context.session_id
                        delay = self._get_retry_delay(attempts_used)
                        attempts_used += 1
                        if delay > 0:
                            await asyncio.sleep(delay)
                        continue

                    # Non-401 errors or retry limit exceeded - raise immediately
                    try:
                        err = response.json()
                        # Map "Instructions are not valid" errors to actionable messages
                        if (
                            response.status_code == 400
                            and isinstance(err, dict)
                            and err.get("detail") == "Instructions are not valid"
                        ):
                            err = {
                                "error": "codex_instructions_invalid",
                                "message": (
                                    "Codex backend rejected the instructions field as invalid. "
                                    "This usually happens when custom prompt modifications are incompatible with Codex's validation rules."
                                ),
                                "detail": err.get("detail"),
                                "suggestion": (
                                    "Set prompt_mode to 'codex_default' in your request capabilities "
                                    "(or in config via backends.openai_codex.extra.codex.default_capabilities) "
                                    "to use Codex's default instructions. System prompts are automatically "
                                    "converted to <user_instructions> blocks and do not need to be in the instructions field."
                                ),
                                "original_error": err,
                            }
                    except Exception as json_err:
                        if logger.isEnabledFor(TRACE_LEVEL):
                            logger.log(
                                TRACE_LEVEL,
                                "Failed to parse error response JSON, falling back to text: %s",
                                json_err,
                                exc_info=True,
                                extra={
                                    "backend": "openai-codex",
                                    "session_id": context.session_id,
                                    "model": context.effective_model,
                                    "status_code": response.status_code,
                                },
                            )
                        err = response.text
                    raise HTTPException(status_code=response.status_code, detail=err)

                # Success - break out of retry loop
                response_json = response.json()
                incompatible_tools = self._detect_incompatible_tool_calls(
                    response_json,
                    context,
                )
                if incompatible_tools:
                    if incompatible_tool_retries < self._max_incompatible_tool_retries:
                        incompatible_tool_retries += 1
                        payload_dict = self._append_incompatible_tool_retry_steering(
                            payload_dict,
                            incompatible_tools,
                            context,
                        )
                        logger.info(
                            "Retrying non-streaming Codex request after incompatible tool calls: %s",
                            ", ".join(incompatible_tools),
                            extra={
                                "backend": "openai-codex",
                                "session_id": context.session_id,
                                "model": context.effective_model,
                                "retry_count": incompatible_tool_retries,
                            },
                        )
                        response_json = None
                        continue
                    logger.warning(
                        "Incompatible tool calls persisted after retries; returning final response.",
                        extra={
                            "backend": "openai-codex",
                            "session_id": context.session_id,
                            "model": context.effective_model,
                            "tool_names": incompatible_tools,
                        },
                    )
                break

            # Ensure response_json is set (MyPy type narrowing)
            assert (
                response_json is not None
            ), "response_json should be set after successful request"
            assert (
                response is not None
            ), "response should be set after successful request"

            # Verbose raw response diagnostics (TRACE only; avoid str()/slicing on DEBUG)
            if logger.isEnabledFor(TRACE_LEVEL):
                choices_count = len(response_json.get("choices", []))
                response_id = response_json.get("id", "unknown")
                response_model = response_json.get("model", "unknown")
                logger.log(
                    TRACE_LEVEL,
                    "Non-streaming response from Codex: id=%s model=%s choices_count=%d",
                    response_id,
                    response_model,
                    choices_count,
                    extra={
                        "backend": "openai-codex",
                        "session_id": context.session_id,
                        "model": context.effective_model,
                        "response_id": response_id,
                    },
                )
                if choices_count == 0:
                    logger.log(
                        TRACE_LEVEL,
                        "Empty choices in non-streaming response - raw response: %s",
                        str(response_json)[:500],
                        extra={
                            "backend": "openai-codex",
                            "session_id": context.session_id,
                            "model": context.effective_model,
                        },
                    )

            # Parse response using translation service with renderer override
            with OverrideRenderer(renderer_key):
                domain_response = (
                    self._base_connector.translation_service.to_domain_response(
                        response_json, "openai"
                    )
                )

            # Extract response headers
            try:
                response_headers = dict(response.headers)
            except (TypeError, AttributeError) as e:
                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(
                        TRACE_LEVEL,
                        "Failed to extract response.headers, using fallback: %s",
                        e,
                        extra={
                            "backend": "openai-codex",
                            "session_id": context.session_id,
                            "model": context.effective_model,
                        },
                    )
                try:
                    response_headers = dict(getattr(response, "headers", {}) or {})
                except (TypeError, AttributeError) as fallback_err:
                    if logger.isEnabledFor(TRACE_LEVEL):
                        logger.log(
                            TRACE_LEVEL,
                            "Failed to extract fallback headers: %s",
                            fallback_err,
                            extra={
                                "backend": "openai-codex",
                                "session_id": context.session_id,
                                "model": context.effective_model,
                            },
                        )
                    response_headers = {}

            # Build response envelope with usage metadata
            return ResponseEnvelope(
                content=domain_response.model_dump(),
                status_code=response.status_code,
                headers=response_headers,
                usage=domain_response.usage,
                metadata={
                    "backend": "openai-codex",
                    "model": context.effective_model,
                    "session_id": context.session_id,
                },
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                "Unexpected error in non-streaming Codex execution: %s",
                e,
                exc_info=True,
                extra={
                    "backend": "openai-codex",
                    "session_id": context.session_id,
                    "model": context.effective_model,
                },
            )
            raise
        finally:
            # Cleanup compatibility state after non-streaming execution completes
            if self._compatibility_layer and compatibility_state:
                try:
                    await self._compatibility_layer.cleanup_state(compatibility_state)
                except Exception as e:
                    if logger.isEnabledFor(TRACE_LEVEL):
                        logger.log(
                            TRACE_LEVEL,
                            "Compatibility state cleanup failed: %s",
                            e,
                            exc_info=True,
                            extra={
                                "backend": "openai-codex",
                                "session_id": context.session_id,
                                "model": context.effective_model,
                            },
                        )

    async def _execute_streaming(
        self, payload: CodexPayload, context: CodexRequestContext, renderer_key: str
    ) -> StreamingResponseEnvelope:
        """Execute streaming Codex request with authentication retry.

        Args:
            payload: Codex API payload
            context: Request context
            renderer_key: Renderer key for tool text rendering

        Returns:
            Streaming response envelope with retry handling
        """
        url = self._codex_url
        # Derive conversation_id from prompt_cache_key, fallback to session_id
        conversation_id = payload.prompt_cache_key or context.session_id
        headers = self._build_headers(conversation_id, context.session_id)
        payload_dict = payload.model_dump(exclude_none=True)

        headers_holder: dict[str, str] = {}
        current_cancel: list[Callable[[], Awaitable[None]] | None] = [None]

        async def cancel_active_stream() -> None:
            cancel_cb = current_cancel[0]
            if cancel_cb is not None:
                await cancel_cb()

        async def _streaming_iterator() -> AsyncIterator[ProcessedResponse]:
            """Streaming iterator with authentication retry logic."""
            attempts_used = 0
            max_retries = max(0, self._max_retries)
            incompatible_tool_retries = 0
            current_headers = dict(headers)
            current_payload_dict = dict(payload_dict)

            # Get compatibility state from context metadata if available
            # State should always be provided by the facade via CodexRequestContext.metadata
            # when compatibility layer is enabled and successfully applied (see design.md).
            compatibility_state: CompatibilityState | None = None
            if context.metadata and "compatibility_state" in context.metadata:
                state_value = context.metadata["compatibility_state"]
                if isinstance(state_value, CompatibilityState):
                    compatibility_state = state_value

            stream_handle = None
            try:
                while True:
                    try:
                        stream_handle = (
                            await self._transport.initiate_streaming_request(
                                url,
                                current_payload_dict,
                                current_headers,
                                context.session_id,
                            )
                        )
                        # Fall through to consume the stream iterator below
                    except HTTPException as exc:
                        if exc.status_code == 401:
                            if attempts_used >= max_retries:
                                # Notify connector of authentication failure for degradation
                                degrade_method = getattr(
                                    self._base_connector, "_degrade", None
                                )
                                if degrade_method is not None:
                                    degrade_method(
                                        [
                                            f"Codex streaming request failed authentication during handshake after {attempts_used} attempts"
                                        ]
                                    )
                                raise HTTPException(
                                    status_code=401,
                                    detail={
                                        "error": "openai_codex_stream_auth_failed",
                                        "message": "Codex streaming request failed authentication during handshake and could not be recovered.",
                                        "details": {
                                            "backend": "openai-codex",
                                            "attempts": attempts_used,
                                            "max_retries": max_retries,
                                        },
                                    },
                                )
                            # Use connector's refresh method to ensure consistency and test compatibility
                            refresh_method = getattr(
                                self._base_connector, "_refresh_access_token", None
                            )
                            if (
                                refresh_method
                                and callable(refresh_method)
                                and inspect.iscoroutinefunction(refresh_method)
                            ):
                                refreshed = await refresh_method()
                            else:
                                refreshed = (
                                    await self._credential_manager.refresh_access_token()
                                )
                                # Update connector's api_key so get_headers() returns the new token
                                new_token = self._credential_manager.get_access_token()
                                if new_token and hasattr(
                                    self._base_connector, "api_key"
                                ):
                                    self._base_connector.api_key = new_token
                            if not refreshed:
                                raise HTTPException(
                                    status_code=401,
                                    detail={
                                        "error": "openai_codex_stream_auth_failed",
                                        "message": "Codex streaming request failed authentication during handshake and could not be recovered.",
                                        "details": {
                                            "backend": "openai-codex",
                                            "attempts": attempts_used,
                                            "max_retries": max_retries,
                                        },
                                    },
                                )
                            delay = self._get_retry_delay(attempts_used)
                            attempts_used += 1
                            if delay > 0:
                                await asyncio.sleep(delay)
                            self._refresh_headers_auth(
                                current_headers, conversation_id, context.session_id
                            )
                            continue
                        raise

                    current_cancel[0] = stream_handle.cancel_callback
                    headers_holder.clear()
                    try:
                        headers_holder.update(dict(stream_handle.headers or {}))
                    except (TypeError, AttributeError, ValueError) as e:
                        if logger.isEnabledFor(TRACE_LEVEL):
                            logger.log(
                                TRACE_LEVEL,
                                "Failed to extract response headers from stream: %s",
                                e,
                                exc_info=True,
                                extra={
                                    "backend": "openai-codex",
                                    "session_id": context.session_id,
                                    "model": context.effective_model,
                                },
                            )
                        headers_holder.clear()

                    restart_stream = False
                    retry_for_incompatible_tools = False
                    visible_output_emitted = False
                    with OverrideRenderer(renderer_key):
                        async for processed_chunk in stream_handle.iterator:
                            incompatible_tools = self._detect_incompatible_tool_calls(
                                processed_chunk.content,
                                context,
                            )
                            if incompatible_tools and not visible_output_emitted:
                                if (
                                    incompatible_tool_retries
                                    < self._max_incompatible_tool_retries
                                ):
                                    retry_for_incompatible_tools = True
                                    restart_stream = True
                                    incompatible_tool_retries += 1
                                    current_payload_dict = (
                                        self._append_incompatible_tool_retry_steering(
                                            current_payload_dict,
                                            incompatible_tools,
                                            context,
                                        )
                                    )
                                    logger.info(
                                        "Retrying streaming Codex request after incompatible tool calls: %s",
                                        ", ".join(incompatible_tools),
                                        extra={
                                            "backend": "openai-codex",
                                            "session_id": context.session_id,
                                            "model": context.effective_model,
                                            "retry_count": incompatible_tool_retries,
                                        },
                                    )
                                    break
                                logger.warning(
                                    "Incompatible streaming tool calls persisted after retries; forwarding final stream.",
                                    extra={
                                        "backend": "openai-codex",
                                        "session_id": context.session_id,
                                        "model": context.effective_model,
                                        "tool_names": incompatible_tools,
                                    },
                                )

                            if self._should_retry_for_auth_error(processed_chunk):
                                restart_stream = True
                                logger.info(
                                    "Codex streaming chunk reported authentication failure; attempting token refresh.",
                                    extra={
                                        "backend": "openai-codex",
                                        "session_id": context.session_id,
                                        "model": context.effective_model,
                                        "attempts_used": attempts_used,
                                    },
                                )
                                # If max_retries is 0, raise immediately without yielding the error chunk
                                if max_retries == 0:
                                    if stream_handle.cancel_callback is not None:
                                        with contextlib.suppress(Exception):
                                            await stream_handle.cancel_callback()
                                    # Notify connector of authentication failure for degradation
                                    degrade_method = getattr(
                                        self._base_connector, "_degrade", None
                                    )
                                    if degrade_method is not None:
                                        degrade_method(
                                            [
                                                f"Codex streaming request failed authentication after {attempts_used} attempts"
                                            ]
                                        )
                                    raise HTTPException(
                                        status_code=401,
                                        detail={
                                            "error": "openai_codex_stream_auth_failed",
                                            "message": "Codex streaming request failed authentication and could not be recovered.",
                                            "details": {
                                                "backend": "openai-codex",
                                                "attempts": attempts_used,
                                                "max_retries": max_retries,
                                            },
                                        },
                                    )
                                break

                            # Apply compatibility layer translation if available
                            if self._compatibility_layer and compatibility_state:
                                try:
                                    chunk_wrapper = ProviderStreamChunk(
                                        raw=processed_chunk
                                    )
                                    translated_chunk = await self._compatibility_layer.translate_stream_chunk(
                                        chunk_wrapper, compatibility_state
                                    )
                                    # Extract the translated content
                                    if hasattr(translated_chunk, "raw"):
                                        processed_chunk = cast(
                                            ProcessedResponse, translated_chunk.raw
                                        )
                                    else:
                                        processed_chunk = cast(
                                            ProcessedResponse, translated_chunk
                                        )
                                except Exception as e:
                                    if logger.isEnabledFor(TRACE_LEVEL):
                                        logger.log(
                                            TRACE_LEVEL,
                                            "Compatibility layer translation failed: %s",
                                            e,
                                            exc_info=True,
                                            extra={
                                                "backend": "openai-codex",
                                                "session_id": context.session_id,
                                                "model": context.effective_model,
                                            },
                                        )
                                    # Continue with original chunk on translation failure

                            if self._chunk_has_client_visible_output(processed_chunk):
                                visible_output_emitted = True
                            yield processed_chunk

                    # If stream completed successfully without auth errors, exit retry loop
                    if not restart_stream:
                        break

                    if restart_stream:
                        if stream_handle.cancel_callback is not None:
                            with contextlib.suppress(Exception):
                                await stream_handle.cancel_callback()

                        if retry_for_incompatible_tools:
                            current_cancel[0] = None
                            continue

                        # Check retry limit before attempting refresh
                        # If we've already used all retries, raise exception
                        if attempts_used >= max_retries:
                            # Notify connector of authentication failure for degradation
                            degrade_method = getattr(
                                self._base_connector, "_degrade", None
                            )
                            if degrade_method is not None:
                                degrade_method(
                                    [
                                        f"Codex streaming request failed authentication after {attempts_used} attempts"
                                    ]
                                )
                            raise HTTPException(
                                status_code=401,
                                detail={
                                    "error": "openai_codex_stream_auth_failed",
                                    "message": "Codex streaming request failed authentication and could not be recovered.",
                                    "details": {
                                        "backend": "openai-codex",
                                        "attempts": attempts_used,
                                        "max_retries": max_retries,
                                    },
                                },
                            )

                        # Use connector's refresh method to ensure consistency and test compatibility
                        refresh_method = getattr(
                            self._base_connector, "_refresh_access_token", None
                        )
                        if (
                            refresh_method
                            and callable(refresh_method)
                            and inspect.iscoroutinefunction(refresh_method)
                        ):
                            refreshed = await refresh_method()
                        else:
                            refreshed = (
                                await self._credential_manager.refresh_access_token()
                            )
                            # Update connector's api_key so get_headers() returns the new token
                            new_token = self._credential_manager.get_access_token()
                            if new_token and hasattr(self._base_connector, "api_key"):
                                self._base_connector.api_key = new_token
                        if not refreshed:
                            # Notify connector of authentication failure for degradation
                            degrade_method = getattr(
                                self._base_connector, "_degrade", None
                            )
                            if degrade_method is not None:
                                degrade_method(
                                    [
                                        f"Codex streaming token refresh failed after {attempts_used} attempts"
                                    ]
                                )
                            raise HTTPException(
                                status_code=401,
                                detail={
                                    "error": "openai_codex_stream_auth_failed",
                                    "message": "Codex streaming request failed authentication and could not be recovered.",
                                    "details": {
                                        "backend": "openai-codex",
                                        "attempts": attempts_used,
                                        "max_retries": max_retries,
                                    },
                                },
                            )

                        delay = self._get_retry_delay(attempts_used)
                        attempts_used += 1
                        if delay > 0:
                            await asyncio.sleep(delay)
                        self._refresh_headers_auth(
                            current_headers, conversation_id, context.session_id
                        )
                        # Restart the stream by continuing the outer while loop
                        continue

                    current_cancel[0] = None
                    return
            finally:
                # Cleanup compatibility state after streaming completes
                if self._compatibility_layer and compatibility_state:
                    try:
                        await self._compatibility_layer.cleanup_state(
                            compatibility_state
                        )
                    except Exception as e:
                        if logger.isEnabledFor(TRACE_LEVEL):
                            logger.log(
                                TRACE_LEVEL,
                                "Compatibility state cleanup failed: %s",
                                e,
                                exc_info=True,
                                extra={
                                    "backend": "openai-codex",
                                    "session_id": context.session_id,
                                    "model": context.effective_model,
                                },
                            )

        return StreamingResponseEnvelope(
            content=_streaming_iterator(),
            media_type="text/event-stream",
            headers=headers_holder,
            cancel_callback=cancel_active_stream,
            metadata={
                "backend": "openai-codex",
                "model": context.effective_model,
                "session_id": context.session_id,
            },
        )

    def _build_headers(self, conversation_id: str, session_id: str) -> dict[str, str]:
        """Build Codex-specific HTTP headers.

        Args:
            conversation_id: Conversation identifier (from prompt_cache_key)
            session_id: Session identifier (proxy correlation ID)

        Returns:
            Headers dictionary
        """
        # Get base headers from connector (includes Authorization)
        base_headers = self._base_connector.get_headers() or {}

        headers = dict(base_headers)
        headers["OpenAI-Beta"] = "responses=experimental"
        headers["Accept"] = "text/event-stream"
        headers["version"] = "0.0.0"  # CODEX_VERSION_HEADER
        headers["originator"] = "codex_cli_rs"  # CODEX_ORIGINATOR

        headers["User-Agent"] = build_codex_user_agent()

        headers["conversation_id"] = conversation_id
        # Codex CLI sends both conversation_id and session_id as the same stable id.
        # Using the proxy correlation id here breaks parity and can lead to backend
        # rejecting cached/session-scoped state. Keep them aligned.
        headers["session_id"] = conversation_id
        headers["Codex-Task-Type"] = "standard"

        # Add account ID if available
        account_id = self._get_account_id()
        if account_id:
            headers["chatgpt-account-id"] = account_id

        return headers

    def _detect_incompatible_tool_calls(
        self,
        response_like: object,
        context: CodexRequestContext,
    ) -> list[str]:
        if not self._compatibility_layer:
            return []
        tool_calls = self._extract_tool_calls(response_like)
        if not tool_calls:
            return []
        return self._compatibility_layer.detect_incompatible_tool_calls(
            tool_calls,
            context,
        )

    def _append_incompatible_tool_retry_steering(
        self,
        payload_dict: dict[str, Any],
        incompatible_tools: list[str],
        context: CodexRequestContext,
    ) -> dict[str, Any]:
        if not self._compatibility_layer or not incompatible_tools:
            return payload_dict
        adapted = self._compatibility_layer.append_incompatible_tool_steering(
            dict(payload_dict),
            incompatible_tools,
            context,
        )
        return dict(adapted)

    @staticmethod
    def _extract_tool_calls(response_like: object) -> list[dict[str, object]]:
        if isinstance(response_like, Mapping):
            item = response_like.get("item")
            if isinstance(item, Mapping):
                return ResponseExecutor._extract_tool_calls(item)

            response_type = response_like.get("type")
            name = response_like.get("name")
            if (
                isinstance(response_type, str)
                and isinstance(name, str)
                and response_type.lower()
                in {"function_call", "custom_tool_call", "local_shell_call"}
                and name.strip()
            ):
                return [{"function": {"name": name.strip()}}]

            direct_calls = response_like.get("tool_calls")
            if isinstance(direct_calls, list):
                return [item for item in direct_calls if isinstance(item, dict)]

            output = response_like.get("output")
            if isinstance(output, list):
                output_tool_calls: list[dict[str, object]] = []
                for output_item in output:
                    output_tool_calls.extend(
                        ResponseExecutor._extract_tool_calls(output_item)
                    )
                if output_tool_calls:
                    return output_tool_calls

            choices = response_like.get("choices")
            if isinstance(choices, list):
                extracted: list[dict[str, object]] = []
                for choice in choices:
                    if not isinstance(choice, Mapping):
                        continue
                    for container_key in ("message", "delta"):
                        container = choice.get(container_key)
                        if not isinstance(container, Mapping):
                            continue
                        tool_calls = container.get("tool_calls")
                        if isinstance(tool_calls, list):
                            extracted.extend(
                                item for item in tool_calls if isinstance(item, dict)
                            )
                return extracted

        metadata = getattr(response_like, "metadata", None)
        if isinstance(metadata, Mapping):
            tool_calls = metadata.get("tool_calls")
            if isinstance(tool_calls, list):
                return [item for item in tool_calls if isinstance(item, dict)]
        content = getattr(response_like, "content", None)
        if content is not None and content is not response_like:
            return ResponseExecutor._extract_tool_calls(content)
        return []

    @staticmethod
    def _chunk_has_client_visible_output(chunk: ProcessedResponse) -> bool:
        content = chunk.content
        if isinstance(content, str):
            return bool(content.strip())
        if isinstance(content, bytes):
            return bool(content.strip())
        if not isinstance(content, Mapping):
            return False
        choices = content.get("choices")
        if not isinstance(choices, list):
            return False
        for choice in choices:
            if not isinstance(choice, Mapping):
                continue
            for container_key in ("delta", "message"):
                container = choice.get(container_key)
                if not isinstance(container, Mapping):
                    continue
                text = container.get("content")
                if isinstance(text, str) and text.strip():
                    return True
        return False

    def _refresh_headers_auth(
        self, headers: dict[str, str], conversation_id: str, session_id: str
    ) -> None:
        """Update headers in place with latest auth token.

        Args:
            headers: Headers dictionary to update
            conversation_id: Conversation identifier (from prompt_cache_key)
            session_id: Session identifier (proxy correlation ID)
        """
        fresh_headers = self._base_connector.get_headers() or {}
        for key, value in fresh_headers.items():
            headers[key] = value
        # Ensure conversation metadata stays aligned
        headers["conversation_id"] = conversation_id
        headers["session_id"] = conversation_id

    def _should_retry_for_auth_error(self, chunk: ProcessedResponse | Any) -> bool:
        """Check if a streaming chunk indicates an authentication failure.

        This method preserves the original connector's heuristic-based detection
        to ensure streaming retry parity (Requirement 1.2, 7.2).

        Args:
            chunk: Processed response chunk

        Returns:
            True if authentication error detected
        """
        content = getattr(chunk, "content", None)
        if content is None:
            content = chunk

        if not isinstance(content, Mapping):
            return False

        # Primary signal: explicit error payload from translation layer
        error_flag = content.get("error")
        details = content.get("details")

        status = self._extract_status_code(
            details if isinstance(details, Mapping) else None
        )
        if status in {401, 403}:
            return True

        # Some payloads stash status inside nested metadata objects
        if isinstance(details, Mapping):
            metadata = details.get("metadata")
            if isinstance(metadata, Mapping):
                status = self._extract_status_code(metadata)
                if status in {401, 403}:
                    return True

        # Fall back to heuristics based on codes/messages
        code = None
        if isinstance(details, Mapping):  # type: ignore[unreachable]
            code = details.get("code")
        if code is None and isinstance(content, Mapping):  # type: ignore[unreachable]
            code = content.get("code")

        def _is_auth_code(value: Any) -> bool:
            if not isinstance(value, str):
                return False
            lowered = value.lower()
            return any(
                token in lowered
                for token in (
                    "auth",
                    "unauthorized",
                    "invalid_token",
                    "invalid_api_key",
                    "token_expired",
                    "access_denied",
                )
            )

        if _is_auth_code(code):
            return True

        # Check error flag and message for auth-related keywords
        for candidate in (error_flag, content.get("message")):
            if isinstance(candidate, str):
                lowered = candidate.lower()
                if "401" in lowered or "403" in lowered or "unauthorized" in lowered:
                    return True
                if "token" in lowered and "expired" in lowered:
                    return True

        return False

    @staticmethod
    def _extract_status_code(payload: Mapping[str, Any] | None) -> int | None:
        """Extract HTTP status code from error payload.

        Args:
            payload: Error payload dictionary

        Returns:
            Status code or None
        """
        if not isinstance(payload, Mapping):
            return None
        for key in ("status", "status_code", "http_status", "code"):
            if key not in payload:
                continue
            value = payload.get(key)
            if isinstance(value, int):
                if 100 <= value <= 599:
                    return value
            elif isinstance(value, str):
                stripped = value.strip()
                if stripped.isdigit():
                    numeric = int(stripped)
                    if 100 <= numeric <= 599:
                        return numeric
        return None

    def _get_retry_delay(self, attempt_index: int) -> float:
        """Get delay for retry attempt.

        Args:
            attempt_index: Zero-based attempt index

        Returns:
            Delay in seconds
        """
        if attempt_index < 0:
            return 0.0
        if not self._retry_backoff_seconds:
            return 0.0
        if attempt_index < len(self._retry_backoff_seconds):
            return self._retry_backoff_seconds[attempt_index]
        return self._retry_backoff_seconds[-1]

    def _get_account_id(self) -> str | None:
        """Get ChatGPT account ID from credentials.

        Returns:
            Account ID or None
        """
        # Try to get account ID from credential manager (preferred)
        account_id = self._credential_manager.get_account_id()
        return account_id

    def _select_renderer_key(self, capabilities: CodexClientCapabilities) -> str:
        """Select renderer key from capabilities.

        This matches the original connector's _select_renderer_key behavior.
        The capabilities should already have tool_text_format set from renderer_default
        during settings loading, so we use "none" as the fallback.

        Args:
            capabilities: Client capabilities with tool_text_format

        Returns:
            Renderer key string
        """
        # Get tool_text_format from capabilities
        # Note: capabilities.tool_text_format should already be set from renderer_default
        # during settings loading, so if it's None/empty, we fall back to "none"
        preferred = capabilities.tool_text_format or "none"
        preferred = preferred.strip()

        if not preferred:
            return "none"

        # Handle "default" and "inherit" as special values that mean "use default"
        # Since we don't have access to connector's _renderer_default here,
        # and capabilities should already have the correct value, we treat these as "none"
        if preferred.lower() in {"default", "inherit"}:
            return "none"

        return preferred
