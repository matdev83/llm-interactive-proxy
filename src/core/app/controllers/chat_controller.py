"""
Chat Controller

Handles all chat completion related API endpoints.
"""

import asyncio
import logging
from typing import Any, cast

from fastapi import HTTPException, Request, Response

from src.core.app.controllers.request_processor_resolver import (
    resolve_request_processor,
)
from src.core.common.exceptions import InitializationError, LLMProxyError
from src.core.domain.chat import (
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatRequest,
    ChatResponse,
    ToolCall,
)
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.translation_service_interface import ITranslationService
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
        request_processor: IRequestProcessor,
        translation_service: ITranslationService | None = None,
        wire_capture: Any | None = None,
    ) -> None:
        """Initialize the controller.

        Args:
            request_processor: The request processor service
            translation_service: Optional translation service
            wire_capture: Optional wire capture service
        """
        self._processor = request_processor
        self._translation_service = (
            translation_service
            if translation_service is not None
            else self._resolve_translation_service_from_provider(None)
        )
        self._wire_capture = wire_capture

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
            except Exception as exc:  # pragma: no cover - diagnostic fallback
                logger.debug(
                    "Translation service lookup failed for %s: %s",
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
            logger.debug(
                "Global TranslationService resolution failed: %s", exc, exc_info=True
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
            except Exception:  # pragma: no cover - diagnostic fallback
                logger.debug(
                    "Failed to update global provider during translation resolution",
                    exc_info=True,
                )

            resolved = _try_get(fallback_provider, cast(type, ITranslationService))
            if resolved is not None:
                return resolved

            resolved = _try_get(fallback_provider, cast(type, TranslationService))
            if resolved is not None:
                return resolved
        except Exception as exc:  # pragma: no cover - defensive fallback
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

        if isinstance(content, str):
            return content

        if isinstance(content, bytes | bytearray):
            return content.decode("utf-8", errors="ignore")

        if hasattr(content, "model_dump"):
            try:
                dumped = content.model_dump()
            except Exception:  # pragma: no cover - defensive
                dumped = None
            if dumped is not None:
                return ChatController._coerce_message_content_to_text(
                    dumped, _depth + 1
                )

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

        if hasattr(content, "text"):
            text_attr = content.text
            if isinstance(text_attr, str):
                return text_attr
            if isinstance(text_attr, bytes | bytearray):
                return text_attr.decode("utf-8", errors="ignore")

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
            except Exception:
                raw_body_bytes = b""
            if raw_body_bytes:
                preview = raw_body_bytes[:1024]
                try:
                    rendered_preview = preview.decode("utf-8", errors="replace")
                except Exception:
                    rendered_preview = repr(preview)
                logger.debug(
                    "Incoming /chat/completions raw request (len=%d): %s%s",
                    len(raw_body_bytes),
                    rendered_preview,
                    "..." if len(raw_body_bytes) > len(preview) else "",
                )

            logger.info(
                f"Handling chat completion request: model={domain_request.model}, processor_type={type(self._processor).__name__}, processor_id={id(self._processor)}"
            )
            if self._processor is None:
                raise HTTPException(status_code=500, detail="Processor is None")

            # Special-case ZAI: delegate non-streaming calls through Anthropic controller path
            # to ensure identical headers/payload behavior as /anthropic/v1/messages
            try:
                from src.core.domain.model_utils import parse_model_backend
            except Exception:
                parse_model_backend = None  # type: ignore[assignment]

            if (
                not getattr(domain_request, "stream", False)
                and parse_model_backend is not None
                and parse_model_backend(str(domain_request.model or ""))[0]
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

                    _, parsed_model = parse_model_backend(
                        str(domain_request.model or ""),
                        default_backend="zai-coding-plan",
                    )
                    normalized_model = parsed_model if parsed_model else "glm-4.6"

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
                    from src.core.interfaces.di_interface import IServiceProvider

                    sp = await _gspd(request)
                    service_provider = _cast(IServiceProvider, sp)

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
                    except Exception:
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
                    return domain_response_to_fastapi(domain_resp)
                except Exception as _e:  # On any failure, fall back to default path
                    logger.debug(
                        f"ZAI delegation fallback due to error: {_e}", exc_info=True
                    )

            # Convert FastAPI Request to RequestContext and process via core processor
            ctx = fastapi_to_domain_request_context(request, attach_original=True)
            # Attach domain request so session resolver can read session_id/extra_body
            import contextlib

            with contextlib.suppress(Exception):
                ctx.domain_request = domain_request  # type: ignore[attr-defined]
                if raw_body_bytes:
                    ctx.raw_body = raw_body_bytes  # type: ignore[attr-defined]

            # Ensure session_id is available in context if provided in request
            if domain_request.session_id:
                ctx.session_id = domain_request.session_id

            # Capture inbound request for wire capture debugging
            if self._wire_capture and self._wire_capture.enabled():
                try:
                    await self._wire_capture.capture_inbound_request(
                        context=ctx,
                        session_id=getattr(ctx, "session_id", None),
                        request_payload=domain_request,
                        raw_body=raw_body_bytes or None,
                    )
                except Exception:
                    logger.debug("Wire capture (inbound request) failed", exc_info=True)

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
                try:
                    # If domain ChatResponse, convert to dict first
                    if isinstance(content, ChatResponse):
                        content = content.model_dump()

                    # If already in expected schema, return as-is
                    if isinstance(content, dict) and "choices" in content:
                        return content

                    # If metadata contains tool_calls, construct OpenAI response preserving them
                    if metadata and isinstance(metadata, dict):
                        tool_calls = metadata.get("tool_calls")
                        if tool_calls:
                            import json as _json
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
                                potential_text = content.get("content") if isinstance(content.get("content"), str) else None  # type: ignore[assignment]
                                if potential_text:
                                    text_content = potential_text

                            # Use Pydantic models instead of manual dict construction
                            # Create the message using Pydantic model
                            message = ChatCompletionChoiceMessage(
                                role="assistant",
                                content=text_content,
                                tool_calls=cast("list[ToolCall] | None", tool_calls),
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

                            # Create the response using Pydantic model
                            response = ChatResponse(
                                id=response_id,
                                created=created_val,
                                model=model_name,
                                choices=[choice],
                                usage=cast(
                                    "dict[str, Any] | None",
                                    metadata.get(
                                        "usage",
                                        {
                                            "prompt_tokens": 0,
                                            "completion_tokens": 0,
                                            "total_tokens": 0,
                                        },
                                    ),
                                ),
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

                                response = ChatResponse(
                                    id=response_id,
                                    created=created_val,
                                    model=model_name,
                                    choices=[choice],
                                    usage=(
                                        cast(
                                            "dict[str, Any] | None",
                                            metadata.get("usage"),
                                        )
                                        if metadata
                                        else {
                                            "prompt_tokens": 0,
                                            "completion_tokens": 0,
                                            "total_tokens": 0,
                                        }
                                    ),
                                )

                                return response.model_dump()
                        except Exception:
                            # If parsing fails, continue to other handlers
                            pass

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
                            usage=openai_usage,
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
                            text = _json.dumps(content)
                        except Exception:
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

                    # Create the response using Pydantic model
                    response = ChatResponse(
                        id=f"chatcmpl-{uuid.uuid4().hex[:16]}",
                        created=int(time.time()),
                        model=getattr(domain_request, "model", "gpt-4"),
                        choices=[choice],
                        usage={
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "total_tokens": 0,
                        },
                    )

                    return response
                except Exception:
                    return content

            return domain_response_to_fastapi(
                response, content_converter=_ensure_openai_chat_schema
            )

        except LLMProxyError as e:
            # Map domain exceptions to HTTP exceptions
            raise map_domain_exception_to_http_exception(e)
        except HTTPException:
            # Re-raise HTTP exceptions
            raise
        except Exception as e:
            # Log and convert other exceptions to HTTP exceptions
            logger.error(f"Error handling chat completion: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail={"error": {"message": str(e), "type": "server_error"}},
            )


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

    return ChatController(request_processor)
