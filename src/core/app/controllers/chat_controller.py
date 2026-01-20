"""
Chat Controller

Handles all chat completion related API endpoints.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, cast

from fastapi import HTTPException, Request, Response

from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.app.controllers.request_processor_resolver import (
    resolve_request_processor,
)
from src.core.common.exceptions import (
    InitializationError,
    LLMProxyError,
    ServiceResolutionError,
)
from src.core.domain.chat import (
    CanonicalChatRequest,
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatRequest,
    ChatResponse,
    ToolCall,
)
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.session_metrics_initializer_interface import (
    ISessionMetricsInitializer,
)
from src.core.interfaces.translation_service_interface import ITranslationService
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.transport.fastapi.exception_adapters import (
    map_domain_exception_to_http_exception,
)
from src.core.transport.fastapi.request_adapters import (
    fastapi_to_domain_request_context,
)
from src.core.transport.fastapi.response_adapters import domain_response_to_fastapi

logger = logging.getLogger(__name__)


class ChatController:
    """Controller for chat-related endpoints."""

    def __init__(
        self,
        request_processor: IRequestProcessor | None,
        translation_service: ITranslationService | None = None,
        wire_capture: Any | None = None,
        metrics_initializer: ISessionMetricsInitializer | None = None,
    ) -> None:
        """Initialize the controller.

        Args:
            request_processor: The request processor service
            translation_service: Optional translation service
            wire_capture: Optional wire capture service
            metrics_initializer: Optional session metrics initializer for proactive metrics creation
        """
        self._processor = request_processor
        self._translation_service = (
            translation_service
            if translation_service is not None
            else self._resolve_translation_service_from_provider(None)
        )
        self._wire_capture = wire_capture
        self._metrics_initializer = metrics_initializer

    @staticmethod
    def _resolve_translation_service_from_provider(
        provider: IServiceProvider | None,
    ) -> ITranslationService:
        """Resolve TranslationService through DI when available."""

        from src.core.services.translation_service import TranslationService

        def _try_get(
            svc_provider: IServiceProvider,
            key: type,
        ) -> ITranslationService | None:
            try:
                service = svc_provider.get_service(key)
            except (RuntimeError, AttributeError, TypeError, ValueError) as exc:
                # Expected exceptions from service resolution (factory errors, type mismatches, etc.)
                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(
                        TRACE_LEVEL,
                        "Translation service lookup failed for %s: %s",
                        getattr(key, "__name__", repr(key)),
                        exc,
                        exc_info=True,
                    )
                return None
            except (
                Exception
            ) as exc:  # pragma: no cover - defensive guard for unexpected errors
                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(
                        TRACE_LEVEL,
                        "Translation service lookup failed for %s (unexpected error): %s",
                        getattr(key, "__name__", repr(key)),
                        exc,
                        exc_info=True,
                    )
                return None
            if service is None:
                return None
            return cast(ITranslationService, service)

        if provider is not None:
            resolved = _try_get(provider, cast(type, ITranslationService))
            if resolved is not None:
                return resolved
            resolved = _try_get(provider, cast(type, TranslationService))
            if resolved is not None:
                return resolved

        try:
            from src.core.di.services import get_service_provider

            global_provider = get_service_provider()
        except Exception as exc:  # pragma: no cover - diagnostic fallback
            if logger.isEnabledFor(TRACE_LEVEL):
                logger.log(
                    TRACE_LEVEL,
                    "Global TranslationService resolution failed: %s",
                    exc,
                    exc_info=True,
                )
        else:
            if global_provider is not provider:
                resolved = _try_get(global_provider, cast(type, ITranslationService))
                if resolved is not None:
                    return resolved
                resolved = _try_get(global_provider, cast(type, TranslationService))
                if resolved is not None:
                    return resolved

        try:
            from src.core.di.services import (
                get_service_collection,
                set_service_provider,
            )

            services = get_service_collection()
            fallback_provider = services.build_service_provider()
            try:
                set_service_provider(fallback_provider)
            except (RuntimeError, AttributeError, TypeError, ValueError) as exc:
                # Expected exceptions from service provider operations
                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(
                        TRACE_LEVEL,
                        "Failed to update global provider during translation resolution: %s",
                        exc,
                        exc_info=True,
                    )
            except (
                Exception
            ) as exc:  # pragma: no cover - defensive guard for unexpected errors
                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(
                        TRACE_LEVEL,
                        "Failed to update global provider during translation resolution (unexpected error): %s",
                        exc,
                        exc_info=True,
                    )

            resolved = _try_get(fallback_provider, cast(type, ITranslationService))
            if resolved is not None:
                return resolved

            resolved = _try_get(fallback_provider, cast(type, TranslationService))
            if resolved is not None:
                return resolved
        except Exception as exc:  # pragma: no cover - defensive fallback
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Unable to resolve TranslationService via DI fallback: %s",
                    exc,
                    exc_info=True,
                )

        raise InitializationError("Translation service is not registered in DI")

    @staticmethod
    def _coerce_message_content_to_text(content: Any, _depth: int = 0) -> str:
        """Flatten ChatMessage content into a plain text payload for Anthropic."""
        # Prevent stack overflow from circular references
        if _depth > 20:
            return f"[Circular reference detected at depth {_depth}]"

        if content is None:
            return ""

        # Handle basic string types first (most common case)
        if isinstance(content, str):
            return content

        # Handle bytes and bytearray types
        if isinstance(content, bytes | bytearray):
            return content.decode("utf-8", errors="ignore")

        # Handle objects with text attribute using explicit type checking
        # We need to be careful here to avoid type checker issues with subclasses
        has_text_attr = hasattr(content, "text")
        if has_text_attr:
            # Use getattr with a default to avoid type checker issues
            try:
                text_attr = getattr(content, "text", None)
                if text_attr is not None:
                    if isinstance(text_attr, str):
                        return text_attr
                    if isinstance(text_attr, bytes | bytearray):
                        return text_attr.decode("utf-8", errors="ignore")
            except (AttributeError, UnicodeDecodeError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Unable to access text attribute: %s",
                        e,
                        exc_info=True,
                    )
                # If we can't access the text attribute, continue with other processing

        # Handle objects with model_dump method
        if hasattr(content, "model_dump"):
            try:
                dumped = content.model_dump()
            except (AttributeError, TypeError, RuntimeError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "model_dump() failed on content object: %s",
                        e,
                        exc_info=True,
                    )
                dumped = None
            if dumped is not None:
                return ChatController._coerce_message_content_to_text(
                    dumped, _depth + 1
                )

        # Handle dictionary objects
        if isinstance(content, dict):
            text_value = content.get("text")
            if isinstance(text_value, str):
                return text_value
            if isinstance(text_value, bytes | bytearray):
                return text_value.decode("utf-8", errors="ignore")

            if content.get("type") == "image_url":
                image_payload = content.get("image_url")
                if isinstance(image_payload, dict):
                    url_value = image_payload.get("url")
                    if isinstance(url_value, str):
                        return url_value

            import json

            try:
                return json.dumps(content, ensure_ascii=False)
            except (TypeError, ValueError) as exc:
                error_message = str(exc)
                if "Circular reference detected" in error_message:
                    return f"[Circular reference detected at depth {_depth}]"
                return error_message or str(content)

        # Handle sequences (lists and tuples)
        # Check if it's a sequence but not a string/bytes/bytearray to avoid conflicts
        if isinstance(content, list | tuple) and not isinstance(
            content, str | bytes | bytearray
        ):
            parts: list[str] = []
            for part in content:
                text_part = ChatController._coerce_message_content_to_text(
                    part, _depth + 1
                )
                if text_part:
                    parts.append(text_part)
            return "\n\n".join(parts)

        # Fallback to string representation
        return str(content)

    async def handle_chat_completion(
        self,
        request: Request,
        request_data: ChatRequest,
    ) -> Response:
        """Handle chat completion requests.

        Args:
            request: The HTTP request
            request_data: The parsed request data as a ChatRequest

        Returns:
            An HTTP response
        """
        try:
            # Use already-validated request_data instead of re-parsing
            domain_request = request_data

            try:
                raw_body_bytes = await request.body()
            except (asyncio.TimeoutError, RuntimeError, HTTPException) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        f"Failed to read request body: {e}",
                        exc_info=True,
                    )
                raw_body_bytes = b""
            if raw_body_bytes:
                preview = raw_body_bytes[:1024]
                try:
                    rendered_preview = preview.decode("utf-8", errors="replace")
                except (UnicodeDecodeError, AttributeError) as e:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            f"Failed to decode request body preview: {e}",
                            exc_info=True,
                        )
                    rendered_preview = repr(preview)
                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(
                        TRACE_LEVEL,
                        "Incoming /chat/completions raw request (len=%d): %s%s",
                        len(raw_body_bytes),
                        rendered_preview,
                        "..." if len(raw_body_bytes) > len(preview) else "",
                    )

            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    f"Handling chat completion request: model={domain_request.model}, processor_type={type(self._processor).__name__}, processor_id={id(self._processor)}"
                )
            # #region agent log
            _log_path = r"c:\Users\Mateusz\source\repos\llm-interactive-proxy\.cursor\debug.log"
            import json as _json_debug
            import hashlib as _hashlib_debug
            _msg_count = len(domain_request.messages) if domain_request.messages else 0
            _last_msg = str(domain_request.messages[-1].content)[:100] if domain_request.messages else "none"
            _content_hash = _hashlib_debug.md5(str(domain_request.messages).encode()).hexdigest()[:12]
            with open(_log_path, "a", encoding="utf-8") as _f:
                _f.write(_json_debug.dumps({"location": "chat_controller.py:handle_request", "message": "Incoming request", "data": {"model": str(domain_request.model), "msg_count": _msg_count, "stream": getattr(domain_request, "stream", False), "content_hash": _content_hash, "last_msg_preview": _last_msg}, "timestamp": __import__("time").time(), "hypothesisId": "B,C,D"}) + "\n")
            # #endregion
            if self._processor is None:
                raise HTTPException(status_code=500, detail="Processor is None")

            # Special-case ZAI: delegate non-streaming calls through Anthropic controller path
            # to ensure identical headers/payload behavior as /anthropic/v1/messages
            try:
                from src.core.domain.model_utils import parse_model_backend
            except (ImportError, ModuleNotFoundError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        f"Unable to import parse_model_backend: {e}",
                        exc_info=True,
                    )
                parse_model_backend = None  # type: ignore[assignment]

            if (
                not getattr(domain_request, "stream", False)
                and parse_model_backend is not None
                and parse_model_backend(str(domain_request.model or "")).backend_type
                in ("zai-coding-plan", "zai_coding_plan")
            ):
                try:
                    # Build AnthropicMessagesRequest from the OpenAI-style ChatRequest
                    from typing import cast as _cast

                    from src.anthropic_models import (
                        AnthropicMessage,
                        AnthropicMessagesRequest,
                    )
                    from src.core.app.controllers.anthropic_controller import (
                        get_anthropic_controller,
                    )

                    # Normalize message content to str for AnthropicMessage
                    anth_messages = []
                    for m in domain_request.messages:
                        content_str = ChatController._coerce_message_content_to_text(
                            m.content
                        )
                        anth_messages.append(
                            AnthropicMessage(role=m.role, content=content_str)
                        )

                    parsed = parse_model_backend(
                        str(domain_request.model or ""),
                        default_backend="zai-coding-plan",
                    )
                    normalized_model: str = (
                        parsed.model_name if parsed.model_name else "glm-4.6"
                    )

                    anth_req = AnthropicMessagesRequest(
                        model=normalized_model,
                        messages=anth_messages,
                        max_tokens=domain_request.max_tokens or 1024,
                        stream=False,
                        temperature=domain_request.temperature,
                        top_p=domain_request.top_p,
                        top_k=getattr(domain_request, "top_k", None),
                    )

                    # Resolve controller via DI
                    from src.core.app.controllers import (
                        get_service_provider_dependency as _gspd,
                    )

                    sp = await _gspd(request)
                    service_provider = sp  # type: ignore[assignment]

                    translation_service = service_provider.get_service(
                        _cast(type, ITranslationService)
                    )
                    if translation_service is None:
                        from src.core.services.translation_service import (
                            TranslationService as ConcreteTranslationService,
                        )

                        translation_service = service_provider.get_service(
                            ConcreteTranslationService
                        )

                    if translation_service is None:
                        raise InitializationError(
                            "Translation service is not registered in the DI container"
                        )

                    anth_controller = get_anthropic_controller(service_provider)

                    anth_response = await anth_controller.handle_anthropic_messages(
                        request, anth_req
                    )

                    # Extract JSON body
                    body_content = getattr(anth_response, "body", b"")
                    if isinstance(body_content, memoryview):
                        body_content = body_content.tobytes()
                    try:
                        import json as _json

                        anth_json = _json.loads(body_content.decode())
                    except (json.JSONDecodeError, UnicodeDecodeError) as e:
                        if logger.isEnabledFor(TRACE_LEVEL):
                            logger.log(
                                TRACE_LEVEL,
                                "Failed to parse Anthropic JSON response: %s",
                                e,
                                exc_info=True,
                            )
                        return anth_response  # type: ignore[return-value]

                    # Convert Anthropic JSON to domain then return domain response
                    # Use DI-resolved translation service to ensure proper dependency injection
                    resolved_translation_service = (
                        self._resolve_translation_service_from_provider(
                            service_provider
                        )
                    )
                    domain_resp = resolved_translation_service.to_domain_response(
                        anth_json, "anthropic"
                    )

                    # Convert domain response to FastAPI response
                    return domain_response_to_fastapi(
                        domain_resp, wire_capture=self._wire_capture, context=None
                    )
                except Exception as _e:  # On any failure, fall back to default path
                    if logger.isEnabledFor(TRACE_LEVEL):
                        logger.log(
                            TRACE_LEVEL,
                            f"ZAI delegation fallback due to error: {_e}",
                            exc_info=True,
                        )

            # Convert FastAPI Request to RequestContext with typed fields populated
            ctx = fastapi_to_domain_request_context(
                request,
                attach_original=True,
                domain_request=cast(CanonicalChatRequest, domain_request),
                raw_body=raw_body_bytes if raw_body_bytes else None,
            )

            # Set protocol identifier for normalization (Requirement 1.9)
            if not ctx.extensions:
                ctx.extensions = {}
            ctx.extensions["protocol"] = "openai"

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"RequestContext created - headers: {list(ctx.headers.keys())}"
                )

            # Ensure session_id is available in context if provided in request
            if domain_request.session_id:
                ctx.session_id = domain_request.session_id

            # Requirement 5.5: Proactive session metrics initialization
            # Initialize session metrics early in lifecycle before backend work begins
            # This ensures metrics exist for EoS emission even if client disconnects immediately
            # Design.md line 434-437: Two-phase approach - proactive (primary) + defensive fallback
            if self._metrics_initializer is not None and ctx.request_id:
                try:
                    from src.core.transport.session_key_resolver import (
                        resolve_session_key_from_request_context,
                    )

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

            # Capture inbound request for wire capture debugging
            if self._wire_capture and self._wire_capture.enabled():
                try:
                    await self._wire_capture.capture_inbound_request(
                        context=ctx,
                        session_id=getattr(ctx, "session_id", None),
                        request_payload=domain_request,
                        raw_body=raw_body_bytes or None,
                    )
                except OSError as exc:
                    # Expected I/O errors (disk full, permission denied, etc.)
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Wire capture (inbound request) failed: %s",
                            exc,
                            exc_info=True,
                        )
                except (ValueError, TypeError, AttributeError, RuntimeError) as exc:
                    # Expected errors from wire capture (JSON serialization, attribute access, etc.)
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Wire capture (inbound request) failed: %s",
                            exc,
                            exc_info=True,
                        )
                except (
                    Exception
                ) as exc:  # pragma: no cover - defensive guard for unexpected errors
                    # Unexpected errors during wire capture - log at DEBUG level for visibility
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Wire capture (inbound request) failed (unexpected error): %s",
                            exc,
                            exc_info=True,
                        )

            # Process the request using the request processor
            response = await self._processor.process_request(ctx, domain_request)

            # Convert domain response to FastAPI response
            # Ensure we await the response if it's a coroutine
            if asyncio.iscoroutine(response):
                response = await response

            # Ensure OpenAI Chat Completions JSON schema for non-streaming responses
            response_metadata = getattr(response, "metadata", None)

            def _ensure_openai_chat_schema(
                content: object, metadata: dict[str, object] | None = response_metadata
            ) -> object:
                def _inject_reasoning_aliases(payload: object) -> object:
                    if not isinstance(payload, dict):
                        return payload
                    choices = payload.get("choices")
                    if isinstance(choices, list):
                        for choice in choices:
                            if not isinstance(choice, dict):
                                continue
                            message = choice.get("message")
                            if isinstance(message, dict):
                                reasoning_value = message.get("reasoning_content")
                                if reasoning_value and "reasoning" not in message:
                                    message["reasoning"] = reasoning_value
                            delta = choice.get("delta")
                            if isinstance(delta, dict):
                                reasoning_value = delta.get("reasoning_content")
                                if reasoning_value and "reasoning" not in delta:
                                    delta["reasoning"] = reasoning_value
                    return payload

                try:
                    # If domain ChatResponse, convert to dict first
                    if isinstance(content, ChatResponse):
                        content = content.model_dump()

                    # If already in expected schema, return as-is
                    if isinstance(content, dict) and "choices" in content:
                        return _inject_reasoning_aliases(content)

                    # If metadata contains tool_calls, construct OpenAI response preserving them
                    if metadata:
                        tool_calls = metadata.get("tool_calls")  # type: ignore[arg-type]
                        if tool_calls:
                            import time as _time
                            import uuid as _uuid

                            # Attempt to parse textual content to preserve any assistant message text
                            text_content = None
                            if isinstance(content, str):
                                stripped = content.strip()
                                if stripped:
                                    text_content = stripped
                            elif isinstance(content, dict):
                                # If content is partial dict without choices, try to pull text field
                                potential_text = content.get("content") if isinstance(content.get("content"), str) else None  # type: ignore[arg-type, assignment]
                                if potential_text:
                                    text_content = potential_text

                            # Use Pydantic models instead of manual dict construction
                            # Explicitly convert tool_calls to ToolCall objects to handle class mismatch
                            tool_call_objects = []
                            if tool_calls and isinstance(tool_calls, list):
                                for tc in tool_calls:
                                    try:
                                        if isinstance(tc, dict):
                                            tool_call_objects.append(ToolCall(**tc))
                                        elif isinstance(tc, ToolCall):
                                            tool_call_objects.append(tc)
                                        elif hasattr(tc, "model_dump"):
                                            # Handle class mismatch by converting to dict first
                                            tool_call_objects.append(
                                                ToolCall(**tc.model_dump())
                                            )
                                    except Exception as e:
                                        if logger.isEnabledFor(logging.DEBUG):
                                            logger.debug(
                                                f"ToolCall construction failed for item: {e}"
                                            )

                            # Create the message using Pydantic model
                            message = ChatCompletionChoiceMessage(
                                role="assistant",
                                content=text_content,
                                tool_calls=(
                                    tool_call_objects if tool_call_objects else None
                                ),
                            )

                            # Create the choice using Pydantic model
                            choice = ChatCompletionChoice(
                                index=0,
                                message=message,
                                finish_reason=cast(
                                    "str | None",
                                    metadata.get("finish_reason", "tool_calls"),
                                ),
                            )

                            model_name = str(
                                metadata.get("model")
                                or getattr(domain_request, "model", "gpt-4")
                            )
                            response_id = str(
                                metadata.get("id")
                                or f"chatcmpl-{_uuid.uuid4().hex[:16]}"
                            )
                            created_ts = metadata.get("created")
                            if isinstance(created_ts, int | float):
                                created_val = int(created_ts)
                            else:
                                created_val = int(_time.time())

                            from src.core.domain.usage_summary import UsageSummary

                            raw_usage = metadata.get(
                                "usage",
                                {
                                    "prompt_tokens": 0,
                                    "completion_tokens": 0,
                                    "total_tokens": 0,
                                },
                            )
                            usage_summary = None
                            if isinstance(raw_usage, UsageSummary):
                                usage_summary = raw_usage
                            elif isinstance(raw_usage, dict):
                                usage_summary = UsageSummary.from_dict(raw_usage)

                            # Create the response using Pydantic model
                            response = ChatResponse(
                                id=response_id,
                                created=created_val,
                                model=model_name,
                                choices=[choice],
                                usage=usage_summary,
                            )

                            return _inject_reasoning_aliases(response.model_dump())

                    if metadata:
                        meta_role = metadata.get("role")  # type: ignore[arg-type]
                        if meta_role == "tool":
                            import time as _time
                            import uuid as _uuid

                            tool_call_id = metadata.get("tool_call_id")
                            finish_reason = metadata.get("finish_reason") or "stop"

                            model_name = str(
                                metadata.get("model")
                                or getattr(domain_request, "model", "gpt-4")
                            )
                            response_id = str(
                                metadata.get("id")
                                or f"chatcmpl-{_uuid.uuid4().hex[:16]}"
                            )
                            created_ts = metadata.get("created")
                            if isinstance(created_ts, int | float):
                                created_val = int(created_ts)
                            else:
                                created_val = int(_time.time())

                            message_metadata = {
                                k: v
                                for k, v in metadata.items()
                                if k
                                not in {
                                    "role",
                                    "tool_call_id",
                                    "finish_reason",
                                    "model",
                                    "id",
                                    "created",
                                }
                            }
                            if not message_metadata:
                                message_metadata = None  # type: ignore[assignment]

                            message = ChatCompletionChoiceMessage(
                                role="tool",
                                content=str(content or ""),
                                tool_call_id=(
                                    str(tool_call_id) if tool_call_id else None
                                ),
                                metadata=message_metadata,
                            )

                            choice = ChatCompletionChoice(
                                index=0,
                                message=message,
                                finish_reason=finish_reason,  # type: ignore[arg-type]
                            )

                            from src.core.domain.usage_summary import UsageSummary

                            raw_usage = metadata.get("usage")
                            usage_summary = None
                            if isinstance(raw_usage, UsageSummary):
                                usage_summary = raw_usage
                            elif isinstance(raw_usage, dict):
                                usage_summary = UsageSummary.from_dict(raw_usage)

                            response = ChatResponse(
                                id=response_id,
                                created=created_val,
                                model=model_name,
                                choices=[choice],
                                usage=usage_summary,
                            )

                            return response.model_dump()

                    # Check if content is a JSON string of tool calls (common backend response format)
                    if isinstance(content, str):
                        try:
                            import json as _json

                            parsed_content = _json.loads(content)
                            if (
                                isinstance(parsed_content, list)
                                and len(parsed_content) > 0
                                and isinstance(parsed_content[0], dict)
                                and parsed_content[0].get("type") == "function"
                            ):
                                # Content is a tool calls array, create proper OpenAI response
                                import time as _time
                                import uuid as _uuid

                                # Create the message using Pydantic model
                                message = ChatCompletionChoiceMessage(
                                    role="assistant",
                                    content=None,
                                    tool_calls=parsed_content,
                                )

                                choice = ChatCompletionChoice(
                                    index=0,
                                    message=message,
                                    finish_reason="tool_calls",
                                )

                                model_name = str(
                                    metadata.get("model")
                                    if metadata
                                    else getattr(domain_request, "model", "gpt-4")
                                )
                                response_id = str(
                                    metadata.get("id")
                                    if metadata
                                    else None or f"chatcmpl-{_uuid.uuid4().hex[:16]}"
                                )
                                created_ts = (
                                    metadata.get("created") if metadata else None
                                )
                                if isinstance(created_ts, int | float):
                                    created_val = int(created_ts)
                                else:
                                    created_val = int(_time.time())

                                from src.core.domain.usage_summary import UsageSummary

                                if metadata:
                                    raw_usage = metadata.get("usage")
                                else:
                                    raw_usage = {
                                        "prompt_tokens": 0,
                                        "completion_tokens": 0,
                                        "total_tokens": 0,
                                    }
                                usage_summary = None
                                if isinstance(raw_usage, UsageSummary):
                                    usage_summary = raw_usage
                                elif isinstance(raw_usage, dict):
                                    usage_summary = UsageSummary.from_dict(raw_usage)

                                response = ChatResponse(
                                    id=response_id,
                                    created=created_val,
                                    model=model_name,
                                    choices=[choice],
                                    usage=usage_summary,
                                )

                                return response.model_dump()
                        except (ValueError, TypeError) as e:
                            if logger.isEnabledFor(TRACE_LEVEL):
                                logger.log(
                                    TRACE_LEVEL,
                                    "Failed to parse Anthropic message dict: %s",
                                    e,
                                    exc_info=True,
                                )
                            # If parsing fails, continue to other handlers

                    # Handle Anthropic-style message dict -> OpenAI chat.completion
                    if (
                        isinstance(content, dict)
                        and content.get("type") == "message"
                        and isinstance(content.get("content"), list)
                    ):
                        import json as _json
                        import time as _time
                        import uuid as _uuid

                        # Extract text blocks
                        text_parts: list[str] = []
                        tool_calls_list: list[dict] = []
                        for block in content.get("content", []):
                            if not isinstance(block, dict):
                                continue
                            btype = block.get("type")
                            if btype == "text":
                                part_text = block.get("text") or ""
                                if part_text:
                                    text_parts.append(str(part_text))
                            elif btype == "tool_use":
                                # Map to OpenAI tool_calls structure
                                fn_name = block.get("name") or "tool"
                                fn_args = block.get("input") or {}
                                tool_calls_list.append(
                                    {
                                        "id": str(
                                            block.get("id")
                                            or f"call_{_uuid.uuid4().hex[:16]}"
                                        ),
                                        "type": "function",
                                        "function": {
                                            "name": str(fn_name),
                                            "arguments": _json.dumps(fn_args),
                                        },
                                    }
                                )

                        text = "\n\n".join(text_parts).strip()
                        stop_reason = content.get("stop_reason") or "stop"
                        if stop_reason == "end_turn":
                            finish_reason = "stop"
                        elif stop_reason == "max_tokens":
                            finish_reason = "length"
                        elif stop_reason == "tool_use":
                            finish_reason = "tool_calls"
                        else:
                            finish_reason = str(stop_reason)

                        usage = content.get("usage") or {}
                        openai_usage = {
                            "prompt_tokens": usage.get("input_tokens", 0),
                            "completion_tokens": usage.get("output_tokens", 0),
                            "total_tokens": (usage.get("input_tokens", 0) or 0)
                            + (usage.get("output_tokens", 0) or 0),
                        }
                        from src.core.domain.usage_summary import UsageSummary

                        # Use Pydantic models instead of manual dict construction
                        # Create the message using Pydantic model
                        message = ChatCompletionChoiceMessage(
                            role="assistant",
                            content=text if text else None,
                            tool_calls=(
                                cast("list[ToolCall] | None", tool_calls_list)
                                if tool_calls_list
                                else None
                            ),
                        )

                        # Create the choice using Pydantic model
                        choice = ChatCompletionChoice(
                            index=0,
                            message=message,
                            finish_reason=finish_reason,
                        )

                        # Create the response using Pydantic model
                        response = ChatResponse(
                            id=content.get("id", f"chatcmpl-{_uuid.uuid4().hex[:16]}"),
                            created=int(_time.time()),
                            model=content.get(
                                "model", getattr(domain_request, "model", "gpt-4")
                            ),
                            choices=[choice],
                            usage=UsageSummary.from_dict(openai_usage),
                        )

                        return response

                    import json as _json
                    import time
                    import uuid

                    # Normalize simple string into OpenAI-like response
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, bytes):
                        text = content.decode("utf-8", errors="ignore")
                    else:
                        # Best-effort stringify for non-dict/list types
                        try:
                            # Use dict() for dict types to safely handle StopChunkWithUsage
                            safe_content = (
                                dict(content) if isinstance(content, dict) else content
                            )
                            text = _json.dumps(safe_content)
                        except (TypeError, ValueError) as e:
                            if logger.isEnabledFor(TRACE_LEVEL):
                                logger.log(
                                    TRACE_LEVEL,
                                    "Failed to JSON-serialize content, falling back to str: %s",
                                    e,
                                    exc_info=True,
                                )
                            text = str(content)

                    # Fallback: treat remaining content as assistant text
                    # Use Pydantic models instead of manual dict construction
                    # Create the message using Pydantic model
                    message = ChatCompletionChoiceMessage(
                        role="assistant",
                        content=text,
                    )

                    # Create the choice using Pydantic model
                    choice = ChatCompletionChoice(
                        index=0,
                        message=message,
                        finish_reason="stop",
                    )

                    from src.core.domain.usage_summary import UsageSummary

                    # Create the response using Pydantic model
                    response = ChatResponse(
                        id=f"chatcmpl-{uuid.uuid4().hex[:16]}",
                        created=int(time.time()),
                        model=getattr(domain_request, "model", "gpt-4"),
                        choices=[choice],
                        usage=UsageSummary.from_dict(
                            {
                                "prompt_tokens": 0,
                                "completion_tokens": 0,
                                "total_tokens": 0,
                            }
                        ),
                    )

                    return response
                except Exception as e:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Failed to convert response to OpenAI chat schema, returning raw content: %s",
                            e,
                            exc_info=True,
                        )
                    return content

            return domain_response_to_fastapi(
                response,
                content_converter=_ensure_openai_chat_schema,
                wire_capture=self._wire_capture,
                context=ctx,
            )

        except LLMProxyError as e:
            # Map domain exceptions to HTTP exceptions
            raise map_domain_exception_to_http_exception(e)
        except HTTPException:
            # Re-raise HTTP exceptions
            raise
        except Exception as e:
            # Log and convert other exceptions to HTTP exceptions
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Error handling chat completion: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail={"error": {"message": str(e), "type": "server_error"}},
            ) from e


def get_chat_controller(service_provider: IServiceProvider) -> ChatController:
    """Create a chat controller using the service provider.

    Args:
        service_provider: The service provider to use

    Returns:
        A configured chat controller

    Raises:
        Exception: If the request processor could not be found or created
    """
    try:
        request_processor = resolve_request_processor(service_provider)
    except InitializationError as exc:
        raise InitializationError("Could not find or create RequestProcessor") from exc

    wire_capture = None

    # Wire capture is optional - get it if available
    try:
        wire_capture = service_provider.get_service(cast(type, IWireCapture))
    except (ServiceResolutionError, AttributeError):
        # Service not registered or provider doesn't have get_service method
        # This is expected when wire capture is disabled
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Wire capture service not available in DI container (service not registered or disabled)",
                exc_info=True,
            )
    except Exception as e:
        # Unexpected error during service resolution - log for debugging
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Unexpected error getting wire capture service, continuing without wire capture: %s",
                e,
                exc_info=True,
            )

    return ChatController(request_processor, wire_capture=wire_capture)
