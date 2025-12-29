"""Responses Controller handling OpenAI Responses API endpoints."""

import asyncio
import contextlib
import logging
import re
import sre_parse
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from sre_constants import MAXREPEAT
from typing import Any, cast

from fastapi import HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from src.core.common.exceptions import (
    InitializationError,
    LLMProxyError,
    TranslationError,
    ParsingError,
)
from src.core.domain.chat import CanonicalChatRequest
from src.core.domain.client_termination import (
    ClientEndOfSessionSignal,
    ClientTerminationReason,
)
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.domain.responses_api import (
    ResponsesRequest,
    enforce_json_schema_limits,
)
from src.core.interfaces.client_end_of_session_service_interface import (
    IClientEndOfSessionService,
)
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.session_metrics_initializer_interface import (
    ISessionMetricsInitializer,
)
from src.core.interfaces.translation_service_interface import (
    ITranslationService,
)
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.services.json_repair_service import enforce_schema_size_limits
from src.core.transport.fastapi.exception_adapters import (
    map_domain_exception_to_http_exception,
)
from src.core.transport.fastapi.request_adapters import (
    fastapi_to_domain_request_context,
)
from src.core.transport.fastapi.response_adapters import domain_response_to_fastapi
from src.core.transport.session_key_resolver import (
    resolve_session_key_from_request_context,
)

logger = logging.getLogger(__name__)


class ResponsesController:
    """Controller for Responses API endpoints."""

    _MAX_REGEX_PATTERN_LENGTH = 512

    def __init__(
        self,
        request_processor: IRequestProcessor,
        translation_service: ITranslationService | None = None,
        wire_capture: IWireCapture | None = None,
        client_eos_service: IClientEndOfSessionService | None = None,
        metrics_initializer: ISessionMetricsInitializer | None = None,
    ) -> None:
        """Initialize the controller.

        Args:
            request_processor: The request processor service
            translation_service: Translation service for request conversion
            wire_capture: Optional wire capture service
            client_eos_service: Optional client end-of-session service for termination reporting
            metrics_initializer: Optional session metrics initializer for proactive metrics creation
        """
        self._processor = request_processor
        if translation_service is None:
            raise InitializationError(
                "Translation service must be provided by DI container"
            )

        self._translation_service = translation_service
        self._wire_capture = wire_capture
        self._client_eos_service = client_eos_service
        self._metrics_initializer = metrics_initializer

    async def handle_responses_request(
        self,
        request: Request,
        request_data: ResponsesRequest | dict[str, Any],
    ) -> Response:
        """Handle Responses API requests.

        Args:
            request: The HTTP request
            request_data: The parsed request data as a ResponsesRequest

        Returns:
            An HTTP response
        """
        responses_request = self._parse_responses_request(request_data)
        request_id = self._resolve_request_id(request)
        has_schema, schema_name = self._validate_schema_if_present(
            request_id=request_id,
            responses_request=responses_request,
        )

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Responses API request received - request_id=%s, model=%s, has_schema=%s, schema_name=%s",
                request_id,
                responses_request.model,
                has_schema,
                schema_name,
            )

        try:
            # Convert ResponsesRequest to internal ChatRequest format using TranslationService
            translation_service = self._translation_service

            # Log schema validation attempt if schema is present
            self._log_schema_validation_attempt(
                request_id=request_id,
                responses_request=responses_request,
                has_schema=has_schema,
                schema_name=schema_name,
            )

            try:
                domain_request = translation_service.to_domain_request(
                    responses_request, source_format="responses"
                )
            except ValidationError as exc:
                raise self._map_validation_error(exc) from exc

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Request translation successful - request_id={request_id}, "
                    f"domain_model={domain_request.model}, processor_type={type(self._processor).__name__}"
                )
            if self._processor is None:
                raise HTTPException(status_code=500, detail="Processor is None")

            ctx = self._build_request_context(
                request=request,
                domain_request=domain_request,
                responses_request=responses_request,
                request_id=request_id,
                schema_name=schema_name,
            )
            # Requirement 5.5: Proactive session metrics initialization
            # Initialize session metrics early in lifecycle before backend work begins
            # This ensures metrics exist for EoS emission even if client disconnects immediately
            # Design.md line 434-437: Two-phase approach - proactive (primary) + defensive fallback
            if self._metrics_initializer is not None and ctx.request_id:
                try:
                    session_key = resolve_session_key_from_request_context(ctx)
                    if session_key is not None:
                        await self._metrics_initializer.ensure_session_metrics(
                            session_key, observed_at=datetime.now(timezone.utc)
                        )
                except Exception as exc:
                    # Requirement 3.9: Fail-open behavior - log but don't raise
                    # Design.md line 413: Log with high-signal error code for visibility
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Failed to initialize session metrics proactively: %s",
                            exc,
                            exc_info=True,
                            extra={
                                "request_id": ctx.request_id,
                                "error_code": "SESSION_METRICS_INIT_FAILED",
                            },
                        )
            # Process request using the request processor
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Processing request through pipeline - request_id={request_id}"
                )
            # Process the request using the request processor
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Processing request through pipeline - request_id={request_id}"
                )
            response = await self._processor.process_request(ctx, domain_request)

            # Convert domain response to FastAPI response
            # Ensure we await the response if it's a coroutine
            if asyncio.iscoroutine(response):
                response = await response

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Request processing completed - request_id={request_id}, response_type={type(response).__name__}"
                )

            # Check if this is a streaming response
            if isinstance(response, StreamingResponseEnvelope):
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        f"Returning streaming response - request_id={request_id}"
                    )

                stream_generator = self._stream_response_envelope(
                    request=request,
                    domain_request=domain_request,
                    response=response,
                    request_id=request_id,
                    context=ctx,
                )

                return StreamingResponse(
                    content=stream_generator,
                    status_code=200,
                    media_type="text/event-stream",
                    headers={
                        "cache-control": "no-cache",
                        "connection": "keep-alive",
                        "content-type": "text/event-stream",
                        "access-control-allow-origin": "*",
                        "access-control-allow-headers": "*",
                    },
                )

            # Convert domain response to Responses API format using TranslationService
            def _ensure_responses_schema(content: object) -> object:
                try:
                    from src.core.domain.chat import ChatResponse

                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            f"Converting response to Responses API format - request_id={request_id}, content_type={type(content).__name__}"
                        )

                    # If it's already a ChatResponse, use TranslationService to convert
                    if isinstance(content, ChatResponse):
                        converted_response = translation_service.from_domain_response(
                            content, target_format="responses"
                        )
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                f"Response converted via TranslationService - request_id={request_id}"
                            )
                        return converted_response

                    # If it's a dict that looks like a ChatResponse, convert it first
                    if isinstance(content, dict) and "choices" in content:
                        try:
                            chat_response = ChatResponse(**content)
                            converted_response = (
                                translation_service.from_domain_response(
                                    chat_response, target_format="responses"
                                )
                            )
                            if logger.isEnabledFor(logging.DEBUG):
                                logger.debug(
                                    f"Response converted from dict via TranslationService - request_id={request_id}"
                                )
                            return converted_response
                        except ValidationError:
                            if logger.isEnabledFor(logging.WARNING):
                                logger.warning(
                                    f"Failed to convert dict to ChatResponse (validation error) - request_id={request_id}",
                                    exc_info=True,
                                )
                            # If conversion fails, fall back to manual conversion
                        except (TranslationError, ParsingError, TypeError, AttributeError, KeyError) as e:
                            # Catch domain exceptions and common data processing errors
                            if logger.isEnabledFor(logging.WARNING):
                                logger.warning(
                                    f"Failed to convert dict to ChatResponse (domain/data error: {type(e).__name__}) - request_id={request_id}",
                                    exc_info=True,
                                )
                            # If conversion fails, fall back to manual conversion
                        except Exception as e:
                            # Catch-all for unexpected errors - log with full context
                            if logger.isEnabledFor(logging.ERROR):
                                logger.error(
                                    f"Unexpected error converting dict to ChatResponse - request_id={request_id}",
                                    exc_info=True,
                                )
                            # If conversion fails, fall back to manual conversion

                    # Fallback: manual conversion for other formats
                    import json as _json
                    import time as _time
                    import uuid as _uuid

                    # If already in expected schema, return as-is
                    # Handle Anthropic-style message dict -> Responses API
                    if (
                        isinstance(content, dict)
                        and content.get("type") == "message"
                        and isinstance(content.get("content"), list)
                    ):
                        # Extract text blocks
                        text_parts: list[str] = []
                        for block in content.get("content", []):
                            if not isinstance(block, dict):
                                continue
                            btype = block.get("type")
                            if btype == "text":
                                part_text = block.get("text") or ""
                                if part_text:
                                    text_parts.append(str(part_text))

                        text = "\n\n".join(text_parts).strip()
                        stop_reason = content.get("stop_reason") or "stop"
                        if stop_reason == "end_turn":
                            finish_reason = "stop"
                        elif stop_reason == "max_tokens":
                            finish_reason = "length"
                        else:
                            finish_reason = str(stop_reason)

                        # Try to parse the content as JSON for structured output
                        parsed = None
                        try:
                            if text.strip():
                                parsed = _json.loads(text)
                                if logger.isEnabledFor(logging.DEBUG):
                                    logger.debug(
                                        f"Successfully parsed structured output - request_id={request_id}"
                                    )
                        except (_json.JSONDecodeError, ValueError) as e:
                            if logger.isEnabledFor(logging.DEBUG):
                                logger.debug(
                                    f"Content is not valid JSON, leaving unparsed - request_id={request_id}, error={e}"
                                )
                            # If parsing fails, leave parsed as None

                        usage = content.get("usage") or {}
                        responses_usage = {
                            "prompt_tokens": usage.get("input_tokens", 0),
                            "completion_tokens": usage.get("output_tokens", 0),
                            "total_tokens": (usage.get("input_tokens", 0) or 0)
                            + (usage.get("output_tokens", 0) or 0),
                        }

                        return {
                            "id": content.get("id", f"resp-{_uuid.uuid4().hex[:16]}"),
                            "object": "response",
                            "created": int(_time.time()),
                            "model": content.get("model", domain_request.model),
                            "choices": [
                                {
                                    "index": 0,
                                    "message": {
                                        "role": "assistant",
                                        "content": text,
                                        "parsed": parsed,
                                    },
                                    "finish_reason": finish_reason,
                                }
                            ],
                            "usage": responses_usage,
                        }

                    # Normalize simple string into Responses API format
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, bytes):
                        text = content.decode("utf-8", errors="ignore")
                    else:
                        # Best-effort stringify for non-dict/list types
                        try:
                            text = _json.dumps(content)
                        except TypeError:
                            # Content is not JSON serializable (e.g., contains custom objects)
                            logger.debug(
                                f"Failed to JSON serialize content, using str - request_id={request_id}",
                                exc_info=True,
                            )
                            text = str(content)

                    # Try to parse the content as JSON for structured output
                    parsed = None
                    try:
                        if text.strip():
                            parsed = _json.loads(text)
                            if logger.isEnabledFor(logging.DEBUG):
                                logger.debug(
                                    f"Successfully parsed fallback structured output - request_id={request_id}"
                                )
                    except (_json.JSONDecodeError, ValueError) as e:
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                f"Fallback content is not valid JSON, leaving unparsed - request_id={request_id}, error={e}"
                            )
                        # If parsing fails, leave parsed as None

                    return {
                        "id": f"resp-{_uuid.uuid4().hex[:16]}",
                        "object": "response",
                        "created": int(_time.time()),
                        "model": domain_request.model,
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": text,
                                    "parsed": parsed,
                                },
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "total_tokens": 0,
                        },
                    }
                except Exception:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            f"Error in response conversion, returning original content - request_id={request_id}",
                            exc_info=True,
                        )
                    return content

            final_response = domain_response_to_fastapi(
                response,
                content_converter=_ensure_responses_schema,
                wire_capture=self._wire_capture,
                context=ctx,
            )

            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    f"Responses API request completed successfully - request_id={request_id}"
                )
            return final_response

        except LLMProxyError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"LLM Proxy error in Responses API - request_id={request_id}, error={e}"
                )
            # Map domain exceptions to HTTP exceptions
            raise map_domain_exception_to_http_exception(e) from e
        except HTTPException as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"HTTP error in Responses API - request_id={request_id}, status={e.status_code}, detail={e.detail}"
                )
            # Re-raise HTTP exceptions
            raise
        except Exception as e:
            # Log and convert other exceptions to HTTP exceptions
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Unexpected error handling Responses API request - request_id={request_id}, error={e}",
                    exc_info=True,
                )
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "message": "An internal server error occurred while processing your request.",
                        "type": "internal_server_error",
                        "code": "internal_error",
                    }
                },
            ) from e


    @staticmethod
    def _resolve_request_id(request: Request) -> str:
        return getattr(request.state, "request_id", None) or f"req-{id(request)}"

    @staticmethod
    def _parse_responses_request(
        request_data: ResponsesRequest | dict[str, Any],
    ) -> ResponsesRequest:
        try:
            responses_request = (
                request_data
                if isinstance(request_data, ResponsesRequest)
                else ResponsesRequest.model_validate(request_data)
            )
            return cast(ResponsesRequest, responses_request)
        except ValidationError as exc:
            raise ResponsesController._map_validation_error(exc) from exc

    def _validate_schema_if_present(
        self, *, request_id: str, responses_request: ResponsesRequest
    ) -> tuple[bool, str | None]:
        response_format = responses_request.response_format
        has_schema = bool(response_format and response_format.json_schema)
        if not (has_schema and response_format and response_format.json_schema):
            return False, None

        json_schema = response_format.json_schema
        schema_name = getattr(json_schema, "name", "unnamed")
        try:
            self._validate_json_schema(json_schema.get_schema())
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "JSON schema validation passed - request_id=%s, schema_name=%s",
                    request_id,
                    schema_name,
                )
        except Exception as exc:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "JSON schema validation failed - request_id=%s, schema_name=%s",
                    request_id,
                    schema_name,
                    exc_info=True,
                )
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "message": f"Invalid JSON schema: {exc!s}",
                        "type": "invalid_schema",
                        "code": "invalid_schema",
                    }
                },
            )

        return True, schema_name

    def _log_schema_validation_attempt(
        self,
        *,
        request_id: str,
        responses_request: ResponsesRequest,
        has_schema: bool,
        schema_name: str | None,
    ) -> None:
        if not logger.isEnabledFor(logging.DEBUG):
            return
        if not has_schema:
            return
        response_format = responses_request.response_format
        json_schema = (
            getattr(response_format, "json_schema", None) if response_format else None
        )
        if json_schema is None:
            return
        logger.debug(
            "Schema validation requested - request_id=%s, schema_name=%s, strict=%s",
            request_id,
            schema_name,
            getattr(json_schema, "strict", True),
        )

    def _build_request_context(
        self,
        *,
        request: Request,
        domain_request: CanonicalChatRequest,
        responses_request: ResponsesRequest,
        request_id: str,
        schema_name: str | None,
    ) -> RequestContext:
        ctx = fastapi_to_domain_request_context(
            request,
            attach_original=True,
            domain_request=domain_request,
        )

        # Set request_id on context for SessionKey resolution (Requirement 1.6)
        ctx.request_id = request_id

        # Set protocol identifier for normalization (Requirement 1.10)
        if ctx.extensions is None:
            ctx.extensions = {}
        ctx.extensions["protocol"] = "openai-responses"

        self._attach_schema_context(
            ctx=ctx,
            responses_request=responses_request,
            request_id=request_id,
            schema_name=schema_name,
        )
        return ctx

    def _attach_schema_context(
        self,
        *,
        ctx: RequestContext,
        responses_request: ResponsesRequest,
        request_id: str,
        schema_name: str | None,
    ) -> None:
        response_format = getattr(responses_request, "response_format", None)
        json_schema = (
            getattr(response_format, "json_schema", None) if response_format else None
        )
        if json_schema is None:
            return

        from src.core.domain.request_context import ProcessingContext

        if ctx.processing_context is None:
            ctx.processing_context = ProcessingContext(values={})

        schema_dict = json_schema.get_schema()
        if not isinstance(schema_dict, dict) or "type" not in schema_dict:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "message": "Invalid JSON schema: missing 'type' field",
                        "type": "invalid_request_error",
                        "code": "invalid_schema",
                    }
                },
            )

        ctx.processing_context.values.update(
            {
                "response_schema": schema_dict,
                "strict_schema_validation": getattr(json_schema, "strict", True),
                "schema_name": getattr(json_schema, "name", "unknown"),
                "request_id": request_id,
            }
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Schema context added to processing pipeline - request_id=%s, schema_name=%s, strict=%s",
                request_id,
                schema_name,
                getattr(json_schema, "strict", True),
            )

    @staticmethod
    def _map_validation_error(exc: ValidationError) -> HTTPException:
        """Convert validation errors into HTTP exceptions with appropriate status codes."""

        errors = exc.errors()
        for error in errors:
            loc = error.get("loc", ())
            if any(part in {"schema", "schema_dict"} for part in loc):
                message = error.get("msg", "Invalid JSON schema")
                if message.lower().startswith("value error, "):
                    message = message[12:]
                return HTTPException(
                    status_code=400,
                    detail={
                        "error": {
                            "message": f"Invalid JSON schema: {message}",
                            "type": "invalid_request_error",
                            "code": "invalid_schema",
                        }
                    },
                )

        # For other validation errors, use OpenAI-style error format
        # Simplify error handling to avoid mypy issues with ValidationError loc field
        return HTTPException(
            status_code=422,
            detail={
                "error": {
                    "message": "Invalid request format. Please check your request parameters and try again.",
                    "type": "invalid_request_error",
                    "code": "invalid_request",
                }
            },
        )

    def _stream_response_envelope(  # noqa: C901
        self,
        request: Request,
        domain_request: Any,
        response: StreamingResponseEnvelope,
        request_id: str,
        context: Any | None = None,
    ) -> AsyncIterator[str]:
        async def _generator() -> AsyncIterator[str]:  # noqa: C901
            import json
            import time
            from datetime import datetime, timezone

            response_id = f"resp_{int(time.time())}_{id(response)}"
            created_timestamp = int(time.time())
            last_chunk_model = getattr(domain_request, "model", "unknown")
            stream_terminated = False

            cancel_lock = asyncio.Lock()
            cancel_state = {"called": False}
            termination_reported = {"reported": False}

            async def report_client_termination(
                termination_reason: ClientTerminationReason,
            ) -> None:
                """Report client termination in shielded context.

                This function ensures termination reporting executes even if
                the request task is cancelled (Requirement 3.6, 3.8).
                """
                # Requirement 1.6: Only report if session context is available
                if context is None:
                    return

                session_key = resolve_session_key_from_request_context(context)
                if session_key is None:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Cannot report client termination: session_key cannot be resolved",
                            extra={"request_id": request_id},
                        )
                    return

                # Deduplicate: only report once per stream
                async with cancel_lock:
                    if termination_reported["reported"]:
                        return
                    termination_reported["reported"] = True

                # Shield termination reporting to ensure it executes even if task is cancelled
                if self._client_eos_service is not None:
                    try:
                        signal = ClientEndOfSessionSignal(
                            session_key=session_key,
                            observed_at=datetime.now(timezone.utc),
                            reason=termination_reason,
                            details=f"HTTP streaming disconnect detected - request_id={request_id}",
                        )
                        # Use asyncio.shield to ensure this executes even if generator is cancelled
                        await asyncio.shield(
                            self._client_eos_service.report_client_termination(signal)
                        )
                    except Exception as exc:
                        # Fail-open: log but don't raise - termination reporting is best-effort
                        # Design.md line 445: Log with high-visibility error code
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Failed to report client termination for streaming disconnect: %s",
                                exc,
                                exc_info=True,
                                extra={
                                    "request_id": request_id,
                                    "session_key": {
                                        "protocol": session_key.protocol,
                                        "primary_id": session_key.primary_id,
                                    },
                                    "error_code": "CLIENT_TERMINATION_REPORT_FAILED",
                                },
                            )

            async def trigger_cancel(reason: str) -> None:
                # Set cancel_reason in RequestContext for normalization (Requirement 3.5, 3.6)
                if context is not None:
                    from src.core.domain.request_context import ProcessingContext

                    if context.processing_context is None:
                        context.processing_context = ProcessingContext(values={})
                    elif context.processing_context.values is None:
                        context.processing_context.values = {}
                    context.processing_context.values["cancel_reason"] = (
                        "client_disconnect"
                        if reason == "client_disconnect"
                        else "stream_cancelled"
                    )

                cancel_cb = response.cancel_callback
                if cancel_cb is None:
                    return

                async with cancel_lock:
                    if cancel_state["called"]:
                        return
                    cancel_state["called"] = True

                try:
                    await cancel_cb()
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Dispatched backend cancellation - request_id=%s, reason=%s",
                            request_id,
                            reason,
                        )
                except Exception as exc:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Failed to propagate cancellation upstream - request_id=%s, reason=%s, error=%s",
                            request_id,
                            reason,
                            exc,
                            exc_info=True,
                        )

            async def is_disconnected() -> bool:
                checker = getattr(request, "is_disconnected", None)
                if checker is None or not callable(checker):
                    return False

                try:
                    result = checker()
                    if asyncio.iscoroutine(result):
                        return bool(await result)
                    return bool(result)
                except Exception:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed checking client disconnect status - request_id=%s",
                            request_id,
                            exc_info=True,
                        )
                    return False

            async def _empty_chunk_iterator() -> AsyncIterator[Any]:
                for _ in []:
                    yield

            chunk_iterator: AsyncIterator[Any] = (
                response.content
                if response.content is not None
                else _empty_chunk_iterator()
            )

            try:
                async for chunk in chunk_iterator:
                    if await is_disconnected():
                        stream_terminated = True
                        # Report client termination before triggering cancellation
                        # (Requirement 1.1, 3.6: detect and report disconnect)
                        await report_client_termination(
                            ClientTerminationReason.CLIENT_DISCONNECTED
                        )
                        await trigger_cancel("client_disconnect")
                        break

                    try:
                        chunk_content = ""
                        chunk_metadata: dict[str, Any] = {}
                        chunk_payload: dict[str, Any] | None = None

                        if isinstance(chunk, ProcessedResponse):
                            chunk_content = chunk.content or ""
                            chunk_metadata = chunk.metadata or {}
                            if isinstance(chunk.content, dict):
                                chunk_payload = chunk.content
                        elif isinstance(chunk, dict):
                            chunk_content = str(chunk.get("content", ""))
                            chunk_metadata = chunk.get("metadata", {}) or {}
                            chunk_payload = chunk
                        elif hasattr(chunk, "content"):
                            chunk_content = getattr(chunk, "content", "") or ""
                            chunk_metadata = getattr(chunk, "metadata", {}) or {}
                            if isinstance(chunk_content, dict):
                                chunk_payload = chunk_content
                        elif isinstance(chunk, str):
                            chunk_content = chunk
                        elif isinstance(chunk, bytes):
                            chunk_content = chunk.decode("utf-8", errors="ignore")
                        else:
                            chunk_content = str(chunk)

                        chunk_id = chunk_metadata.get("id") or response_id
                        chunk_model = chunk_metadata.get("model") or getattr(
                            domain_request, "model", "unknown"
                        )
                        chunk_created = (
                            chunk_metadata.get("created") or created_timestamp
                        )

                        finish_reason = chunk_metadata.get("finish_reason")
                        delta: dict[str, Any] = {}

                        if chunk_payload and isinstance(chunk_payload, dict):
                            chunk_id = chunk_payload.get("id", chunk_id)
                            chunk_model = chunk_payload.get("model", chunk_model)
                            chunk_created = chunk_payload.get("created", chunk_created)

                            choices = chunk_payload.get("choices")
                            if isinstance(choices, list) and choices:
                                primary_choice = choices[0] or {}
                                delta_payload = primary_choice.get("delta") or {}
                                if isinstance(delta_payload, dict):
                                    delta = dict(delta_payload)
                                finish_reason = (
                                    primary_choice.get("finish_reason") or finish_reason
                                )

                        if not delta and chunk_content:
                            delta["content"] = chunk_content

                        content_value = delta.get("content")
                        if content_value is not None and not isinstance(
                            content_value, str
                        ):
                            # Use dict() for dict types to safely handle StopChunkWithUsage
                            safe_value = (
                                dict(content_value)
                                if isinstance(content_value, dict)
                                else content_value
                            )
                            delta["content"] = json.dumps(safe_value)

                        tool_calls = delta.get("tool_calls") or chunk_metadata.get(
                            "tool_calls"
                        )
                        if tool_calls:
                            normalized_calls: list[dict[str, Any]] = []
                            for tool_call in tool_calls:
                                if hasattr(tool_call, "model_dump"):
                                    call_data = tool_call.model_dump()
                                elif isinstance(tool_call, dict):
                                    call_data = dict(tool_call)
                                else:
                                    function = getattr(tool_call, "function", None)
                                    call_data = {
                                        "id": getattr(tool_call, "id", ""),
                                        "type": getattr(tool_call, "type", "function"),
                                        "function": {
                                            "name": getattr(function, "name", ""),
                                            "arguments": getattr(
                                                function, "arguments", "{}"
                                            ),
                                        },
                                    }

                                function_payload = call_data.get("function")
                                if isinstance(function_payload, dict):
                                    arguments = function_payload.get("arguments")
                                    if isinstance(arguments, dict | list):
                                        function_payload["arguments"] = json.dumps(
                                            arguments
                                        )
                                    elif arguments is None:
                                        function_payload["arguments"] = "{}"

                                normalized_calls.append(call_data)

                            delta["tool_calls"] = normalized_calls
                            if logger.isEnabledFor(logging.DEBUG):
                                logger.debug(
                                    "ResponsesController normalized streaming tool_calls: %s",
                                    normalized_calls,
                                )

                        if not delta:
                            delta["content"] = ""

                        choice_payload: dict[str, Any] = {
                            "index": 0,
                            "delta": delta,
                        }
                        if finish_reason:
                            choice_payload["finish_reason"] = finish_reason

                        streaming_chunk = {
                            "id": chunk_id,
                            "object": "response.chunk",
                            "created": chunk_created,
                            "model": chunk_model,
                            "choices": [choice_payload],
                        }

                        last_chunk_model = chunk_model

                        yield f"data: {json.dumps(streaming_chunk)}\n\n"

                    except Exception as exc:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Error processing streaming chunk - request_id=%s, error=%s",
                                request_id,
                                exc,
                                exc_info=True,
                            )
                        continue

                if not stream_terminated:
                    final_chunk = {
                        "id": response_id,
                        "object": "response.chunk",
                        "created": created_timestamp,
                        "model": last_chunk_model,
                        "choices": [
                            {
                                "index": 0,
                                "finish_reason": "stop",
                                "delta": {},
                            }
                        ],
                    }
                    yield f"data: {json.dumps(final_chunk)}\n\n"
                    yield "data: [DONE]\n\n"

            except GeneratorExit:
                # Client disconnected during streaming (Requirement 1.1, 3.6)
                stream_terminated = True
                # Report termination in shielded context (Requirement 3.8)
                try:
                    await asyncio.shield(
                        report_client_termination(
                            ClientTerminationReason.CLIENT_DISCONNECTED
                        )
                    )
                except Exception as exc:
                    # Fail-open: log but continue with cleanup
                    # Design.md line 445: Log with high-visibility error code
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Failed to report client termination in GeneratorExit handler: %s",
                            exc,
                            exc_info=True,
                            extra={
                                "request_id": request_id,
                                "error_code": "CLIENT_TERMINATION_REPORT_FAILED",
                            },
                        )
                await trigger_cancel("client_disconnect")
                raise
            except asyncio.CancelledError:
                stream_terminated = True
                # Report cancellation as client termination (Requirement 1.2, 3.8)
                try:
                    await asyncio.shield(
                        report_client_termination(
                            ClientTerminationReason.CLIENT_CANCELLED
                        )
                    )
                except Exception as exc:
                    # Fail-open: log but continue with cleanup
                    # Design.md line 445: Log with high-visibility error code
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Failed to report client termination in CancelledError handler: %s",
                            exc,
                            exc_info=True,
                            extra={
                                "request_id": request_id,
                                "error_code": "CLIENT_TERMINATION_REPORT_FAILED",
                            },
                        )
                await trigger_cancel("stream_cancelled")
                raise
            except Exception as e:
                if not stream_terminated:
                    await trigger_cancel("stream_error")
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        "Unexpected error in streaming response handler: %s",
                        e,
                        exc_info=True,
                        extra={"request_id": request_id},
                    )
                raise
            finally:
                # Ensure termination is reported even if stream ends abnormally
                # (defensive fallback for edge cases)
                if stream_terminated and not termination_reported["reported"]:
                    try:
                        await asyncio.shield(
                            report_client_termination(
                                ClientTerminationReason.CLIENT_DISCONNECTED
                            )
                        )
                    except Exception as exc:
                        # Fail-open: best-effort reporting
                        # Design.md line 445: Log with high-visibility error code
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Failed to report client termination in finally block: %s",
                                exc,
                                exc_info=True,
                                extra={
                                    "request_id": request_id,
                                    "error_code": "CLIENT_TERMINATION_REPORT_FAILED",
                                },
                            )

                if cancel_state["called"]:
                    close_method = getattr(response.content, "aclose", None)
                    if callable(close_method):
                        with contextlib.suppress(Exception):
                            await close_method()  # type: ignore[misc]

        return _generator()

    @staticmethod
    def _validate_json_schema(schema: dict[str, Any]) -> None:
        """
        Validate a JSON schema for correctness and completeness.

        Args:
            schema: The JSON schema to validate

        Raises:
            ValueError: If the schema is invalid
        """
        if not isinstance(schema, dict):
            raise ValueError("Schema must be a dictionary")

        enforce_schema_size_limits(schema)

        # Check for required fields
        ResponsesController._ensure_safe_regex_patterns(schema)

        if "type" not in schema:
            raise ValueError("Schema must have a 'type' field")

        # Basic structure validation
        schema_type_raw = schema["type"]
        if isinstance(schema_type_raw, str):
            schema_types = [schema_type_raw]
        elif isinstance(schema_type_raw, list | tuple | set):
            schema_types = [
                str(t) for t in schema_type_raw if isinstance(t, str | bytes)
            ]
        else:
            schema_types = [str(schema_type_raw)]

        if "object" in schema_types:
            # Objects can describe their shape via properties, patternProperties,
            # or references. Require at least one structural keyword so callers
            # can use $ref-only schemas without triggering false positives.
            object_keywords = {
                "properties",
                "patternProperties",
                "additionalProperties",
                "$ref",
                "allOf",
                "anyOf",
                "oneOf",
            }
            if not any(key in schema for key in object_keywords):
                raise ValueError(
                    "Object schemas must declare properties, patternProperties, "
                    "additionalProperties, or use a composition/ref keyword"
                )

            properties = schema.get("properties")
            if properties is not None and not isinstance(properties, dict):
                raise ValueError("Properties must be a dictionary")

            if isinstance(properties, dict):
                # Validate each property
                for prop_name, prop_schema in properties.items():
                    if not isinstance(prop_schema, dict):
                        raise ValueError(
                            f"Property '{prop_name}' schema must be a dictionary"
                        )

                    allowed_structural_keywords = {
                        "type",
                        "$ref",
                        "anyOf",
                        "allOf",
                        "oneOf",
                        "enum",
                        "const",
                        "properties",
                        "patternProperties",
                        "items",
                        "contains",
                        "if",
                        "then",
                        "else",
                        "not",
                        "dependentSchemas",
                    }

                    if "type" not in prop_schema and not any(
                        key in prop_schema for key in allowed_structural_keywords
                    ):
                        raise ValueError(
                            f"Property '{prop_name}' must define a type or a "
                            "supported schema keyword"
                        )

        if "array" in schema_types:
            # Arrays should have items; allow both dict schemas and tuple-style lists
            if "items" not in schema:
                raise ValueError("Array schemas must have an 'items' field")

            items_schema = schema["items"]
            if not isinstance(items_schema, dict | list | tuple | bool):
                raise ValueError("Items schema must be a dictionary, list, or boolean")

        primitive_types = {"string", "number", "integer", "boolean", "null"}
        known_types = primitive_types | {"object", "array"}
        unknown_types = [t for t in schema_types if t not in known_types]
        for unknown in unknown_types:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Unusual schema type detected: %s", unknown)

        # Validate additional properties if present
        if "additionalProperties" in schema:
            additional_props = schema["additionalProperties"]
            if not isinstance(additional_props, bool | dict):
                raise ValueError("additionalProperties must be a boolean or schema")

        # Validate required fields if present
        if "required" in schema:
            required = schema["required"]
            if not isinstance(required, list):
                raise ValueError("Required field must be a list")

            # Check if required fields are defined (either directly or via composition)
            if "object" in schema_types:
                # Skip validation if schema uses composition keywords that may define fields
                composition_keywords = {"allOf", "anyOf", "oneOf", "$ref"}
                has_composition = any(key in schema for key in composition_keywords)

                if not has_composition and "properties" in schema:
                    properties = schema["properties"]
                    for req_field in required:
                        if req_field not in properties:
                            raise ValueError(
                                f"Required field '{req_field}' not found in properties"
                            )

        # Validate enum if present
        if "enum" in schema:
            enum_values = schema["enum"]
            if not isinstance(enum_values, list) or len(enum_values) == 0:
                raise ValueError("Enum must be a non-empty list")

        enforce_json_schema_limits(schema)

    @staticmethod
    def _ensure_safe_regex_patterns(schema: dict[str, Any]) -> None:
        """Validate regex patterns in a schema to avoid catastrophic backtracking."""

        stack: list[tuple[Any, str]] = [(schema, "$")]
        visited: set[int] = set()

        while stack:
            node, location = stack.pop()
            node_id = id(node)
            if node_id in visited:
                continue
            visited.add(node_id)

            if isinstance(node, dict):
                pattern = node.get("pattern")
                if isinstance(pattern, str):
                    ResponsesController._validate_single_regex(
                        pattern, f"{location}.pattern"
                    )

                pattern_properties = node.get("patternProperties")
                if isinstance(pattern_properties, dict):
                    for regex_key, sub_schema in pattern_properties.items():
                        if isinstance(regex_key, str):
                            ResponsesController._validate_single_regex(
                                regex_key,
                                f"{location}.patternProperties[{regex_key}]",
                            )
                        if isinstance(sub_schema, dict | list):
                            stack.append(
                                (
                                    sub_schema,
                                    f"{location}.patternProperties.{regex_key}",
                                )
                            )

                for key, value in node.items():
                    if key == "patternProperties":
                        continue
                    if isinstance(value, dict | list):
                        stack.append((value, f"{location}.{key}"))

            elif isinstance(node, list):
                for index, item in enumerate(node):
                    if isinstance(item, dict | list):
                        stack.append((item, f"{location}[{index}]"))

    @staticmethod
    def _validate_single_regex(pattern: str, location: str) -> None:
        """Validate an individual regex for potential ReDoS characteristics."""

        if len(pattern) > ResponsesController._MAX_REGEX_PATTERN_LENGTH:
            raise ValueError(
                "Regex pattern too long: "
                f"{location} has {len(pattern)} characters (limit is {ResponsesController._MAX_REGEX_PATTERN_LENGTH})"
            )

        try:
            parsed = sre_parse.parse(pattern)
        except re.error as exc:  # pragma: no cover - invalid regex handled elsewhere
            raise ValueError(
                f"Invalid regex pattern at {location}: {exc.args[0]}"
            ) from exc

        if ResponsesController._contains_nested_unbounded_repeat(parsed):
            raise ValueError(
                "Regex pattern contains nested unbounded quantifiers which "
                f"can lead to catastrophic backtracking: {location}"
            )

    @staticmethod
    def _contains_nested_unbounded_repeat(
        subpattern: sre_parse.SubPattern, inside_unbounded: bool = False
    ) -> bool:
        """Detect nested unbounded repeats within a parsed regex pattern."""

        # sre_parse.SubPattern is iterable but mypy can't understand this
        for token in cast(list[tuple[Any, Any]], subpattern):  # type: ignore[arg-type]
            operator, argument = token

            if operator in {sre_parse.MAX_REPEAT, sre_parse.MIN_REPEAT}:
                # unpack with type ignore due to mypy not understanding sre_parse tuple structure
                min_repeat, max_repeat, nested = cast(tuple, argument)  # type: ignore[misc]
                is_unbounded = max_repeat == MAXREPEAT

                if inside_unbounded and is_unbounded:
                    return True

                if ResponsesController._contains_nested_unbounded_repeat(
                    cast(sre_parse.SubPattern, nested),
                    inside_unbounded=is_unbounded or inside_unbounded,
                ):
                    return True

                continue

            if operator == sre_parse.SUBPATTERN:
                # argument is a tuple, nested pattern is the last element
                nested = cast(tuple, argument)[-1]  # type: ignore[index]
                if ResponsesController._contains_nested_unbounded_repeat(
                    cast(sre_parse.SubPattern, nested),
                    inside_unbounded=inside_unbounded,
                ):
                    return True
                continue

            if operator == sre_parse.BRANCH:
                # argument is a tuple, second element is list of branches
                _, branches = cast(tuple, argument)  # type: ignore[misc]
                for branch in cast(list, branches):
                    if ResponsesController._contains_nested_unbounded_repeat(
                        cast(sre_parse.SubPattern, branch),
                        inside_unbounded=inside_unbounded,
                    ):
                        return True
                continue

            if operator in {sre_parse.ASSERT, sre_parse.ASSERT_NOT}:
                # argument is a tuple, second element is the nested pattern
                nested = cast(tuple, argument)[1]  # type: ignore[index]
                if ResponsesController._contains_nested_unbounded_repeat(
                    cast(sre_parse.SubPattern, nested),
                    inside_unbounded=inside_unbounded,
                ):
                    return True

        return False


def get_responses_controller(service_provider: IServiceProvider) -> ResponsesController:
    """Create a responses controller using the service provider.

    Args:
        service_provider: The service provider to use

    Returns:
        A configured responses controller

    Raises:
        Exception: If the request processor could not be found or created
    """
    try:
        from src.core.interfaces.wire_capture_interface import IWireCapture
        from src.core.services.request_processor_service import RequestProcessor
        from src.core.services.translation_service import TranslationService

        # Resolve request processor strictly through the DI container.
        request_processor = service_provider.get_service(
            cast(type, IRequestProcessor)
        )  # type: ignore[type-abstract]
        if request_processor is None:
            request_processor = service_provider.get_service(RequestProcessor)

        if request_processor is None:
            raise InitializationError(
                "RequestProcessor is not registered in the service provider",
            )

        # Resolve optional translation service from DI (may be None).
        translation_service = service_provider.get_service(
            cast(type, ITranslationService)
        )  # type: ignore[type-abstract]
        if translation_service is None:
            translation_service = service_provider.get_service(TranslationService)
        if translation_service is None:
            raise InitializationError(
                "TranslationService is not registered in the service provider",
            )

        wire_capture = None
        try:
            wire_capture = service_provider.get_service(cast(type, IWireCapture))
        except (KeyError, AttributeError) as e:
            logger.debug(
                "Wire capture service not available in DI: %s", e, exc_info=True
            )
        except Exception as e:
            logger.warning(
                "Unexpected error getting wire capture service from DI: %s",
                e,
                exc_info=True,
            )

        # Optional: client end-of-session service for termination reporting
        client_eos_service = None
        try:
            from src.core.interfaces.client_end_of_session_service_interface import (
                IClientEndOfSessionService,
            )

            client_eos_service = service_provider.get_service(
                cast(type, IClientEndOfSessionService)
            )
        except (KeyError, AttributeError) as e:
            logger.debug(
                "Client end-of-session service not available in DI: %s",
                e,
                exc_info=True,
            )
        except Exception as e:
            logger.warning(
                "Unexpected error getting client end-of-session service from DI: %s",
                e,
                exc_info=True,
            )

        return ResponsesController(
            request_processor,
            translation_service=translation_service,
            wire_capture=wire_capture,
            client_eos_service=client_eos_service,
        )
    except Exception as e:
        raise InitializationError(f"Failed to create ResponsesController: {e}") from e
