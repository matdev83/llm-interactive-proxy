"""
Chat Controller

Handles all chat completion related API endpoints.
"""

import asyncio
import logging

from fastapi import HTTPException, Request, Response

from src.core.common.exceptions import InitializationError, LLMProxyError
from src.core.domain.chat import ChatRequest, ChatResponse
from src.core.interfaces.backend_request_manager_interface import IBackendRequestManager
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.response_manager_interface import IResponseManager
from src.core.interfaces.session_manager_interface import ISessionManager
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

    def __init__(self, request_processor: IRequestProcessor) -> None:
        """Initialize the controller.

        Args:
            request_processor: The request processor service
        """
        self._processor = request_processor

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
                    from src.core.services.translation_service import (
                        TranslationService,
                    )

                    # Normalize message content to str for AnthropicMessage
                    anth_messages = []
                    for m in domain_request.messages:
                        content_str = m.content if isinstance(m.content, str) else ""
                        anth_messages.append(
                            AnthropicMessage(role=m.role, content=content_str)
                        )

                    anth_req = AnthropicMessagesRequest(
                        model="claude-sonnet-4-20250514",
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
                    anth_controller = get_anthropic_controller(
                        _cast(IServiceProvider, sp)
                    )

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

                    # Convert Anthropic JSON to domain then to OpenAI shape
                    ts = TranslationService()
                    domain_resp = ts.to_domain_response(anth_json, "anthropic")
                    openai_json = ts.from_domain_to_openai_response(domain_resp)

                    from fastapi import Response as _Response

                    return _Response(
                        content=_json.dumps(openai_json),
                        media_type="application/json",
                        status_code=200,
                    )
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

                            openai_message_obj: dict[str, object] = {
                                "role": "assistant",
                                "tool_calls": tool_calls,
                            }
                            if text_content:
                                openai_message_obj["content"] = text_content
                            else:
                                openai_message_obj["content"] = None

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

                            return {
                                "id": response_id,
                                "object": "chat.completion",
                                "created": created_val,
                                "model": model_name,
                                "choices": [
                                    {
                                        "index": 0,
                                        "message": openai_message_obj,
                                        "finish_reason": metadata.get(
                                            "finish_reason", "tool_calls"
                                        ),
                                    }
                                ],
                                "usage": metadata.get(
                                    "usage",
                                    {
                                        "prompt_tokens": 0,
                                        "completion_tokens": 0,
                                        "total_tokens": 0,
                                    },
                                ),
                            }

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

                        message_obj: dict[str, object] = {"role": "assistant"}
                        if text:
                            message_obj["content"] = text
                        if tool_calls_list:
                            message_obj["tool_calls"] = tool_calls_list

                        return {
                            "id": content.get(
                                "id", f"chatcmpl-{_uuid.uuid4().hex[:16]}"
                            ),
                            "object": "chat.completion",
                            "created": int(_time.time()),
                            "model": content.get(
                                "model", getattr(domain_request, "model", "gpt-4")
                            ),
                            "choices": [
                                {
                                    "index": 0,
                                    "message": message_obj,
                                    "finish_reason": finish_reason,
                                }
                            ],
                            "usage": openai_usage,
                        }

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
                    return {
                        "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": getattr(domain_request, "model", "gpt-4"),
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": text},
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
            if logger.isEnabledFor(logging.ERROR):
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
        # Try to get the existing request processor from the service provider
        request_processor = service_provider.get_service(IRequestProcessor)  # type: ignore[type-abstract]
        if request_processor is None:
            # Try to get the concrete implementation
            from src.core.services.request_processor_service import RequestProcessor

            request_processor = service_provider.get_service(RequestProcessor)

        if request_processor is None:
            # If still not found, try to create one on the fly
            from typing import cast

            from src.core.interfaces.backend_processor_interface import (
                IBackendProcessor,
            )
            from src.core.interfaces.backend_service_interface import IBackendService
            from src.core.interfaces.command_processor_interface import (
                ICommandProcessor,
            )
            from src.core.interfaces.command_service_interface import ICommandService
            from src.core.interfaces.response_processor_interface import (
                IResponseProcessor,
            )
            from src.core.interfaces.session_service_interface import ISessionService

            cmd = service_provider.get_service(ICommandService)  # type: ignore[type-abstract]
            backend = service_provider.get_service(IBackendService)  # type: ignore[type-abstract]
            session = service_provider.get_service(ISessionService)  # type: ignore[type-abstract]
            response_proc = service_provider.get_service(IResponseProcessor)  # type: ignore[type-abstract]

            if cmd and backend and session and response_proc:
                from src.core.services.request_processor_service import RequestProcessor

                # Cast the abstract interface types to concrete implementations
                # The service provider is guaranteed to return concrete implementations
                concrete_cmd = cast(ICommandService, cmd)
                concrete_backend = cast(IBackendService, backend)
                concrete_session = cast(ISessionService, session)
                concrete_response_proc = cast(IResponseProcessor, response_proc)
                # Prefer DI-provided processors if available
                di_cmd_proc = service_provider.get_service(ICommandProcessor)  # type: ignore[type-abstract]
                # Get the new decomposed services
                di_session_manager = service_provider.get_service(ISessionManager)  # type: ignore[type-abstract]
                di_backend_request_manager = service_provider.get_service(IBackendRequestManager)  # type: ignore[type-abstract]
                di_response_manager = service_provider.get_service(IResponseManager)  # type: ignore[type-abstract]

                if (
                    di_cmd_proc
                    and di_session_manager
                    and di_backend_request_manager
                    and di_response_manager
                ):
                    # Resolve optional app state for RequestProcessor
                    from src.core.interfaces.application_state_interface import (
                        IApplicationState as _IAppState,
                    )

                    app_state = service_provider.get_required_service(_IAppState)  # type: ignore[type-abstract]
                    request_processor = RequestProcessor(
                        cast(ICommandProcessor, di_cmd_proc),
                        cast(ISessionManager, di_session_manager),
                        cast(IBackendRequestManager, di_backend_request_manager),
                        cast(IResponseManager, di_response_manager),
                        app_state=app_state,
                    )
                else:
                    # Fallback to constructing processors; inject app state where appropriate
                    from src.core.interfaces.application_state_interface import (
                        IApplicationState as _IAppState2,
                    )

                    app_state = service_provider.get_required_service(_IAppState2)  # type: ignore[type-abstract]
                    # Instead of directly instantiating CommandProcessor and BackendProcessor,
                    # we should try to get them from the service provider or register factories
                    # for them in the service collection.
                    # First, try to get them from the service provider
                    command_processor = service_provider.get_service(ICommandProcessor)  # type: ignore[type-abstract]
                    backend_processor = service_provider.get_service(IBackendProcessor)  # type: ignore[type-abstract]

                    # If they are not available, we need to register factories for them
                    if command_processor is None or backend_processor is None:
                        from src.core.di.container import ServiceProvider

                        if isinstance(service_provider, ServiceProvider):
                            try:
                                from src.core.di.services import get_service_collection
                                from src.core.services.backend_processor import (
                                    BackendProcessor,
                                )
                                from src.core.services.command_processor import (
                                    CommandProcessor,
                                )

                                services = get_service_collection()

                                # Register CommandProcessor factory if not already registered
                                if command_processor is None:

                                    def command_processor_factory(
                                        provider: IServiceProvider,
                                    ) -> CommandProcessor:
                                        return CommandProcessor(concrete_cmd)

                                    services.add_singleton(
                                        ICommandProcessor,  # type: ignore[type-abstract]
                                        implementation_factory=command_processor_factory,
                                    )
                                    command_processor = command_processor_factory(
                                        service_provider
                                    )

                                # Register BackendProcessor factory if not already registered
                                if backend_processor is None:

                                    def backend_processor_factory(
                                        provider: IServiceProvider,
                                    ) -> BackendProcessor:
                                        return BackendProcessor(
                                            concrete_backend,
                                            concrete_session,
                                            app_state,
                                        )

                                    services.add_singleton(
                                        IBackendProcessor,  # type: ignore[type-abstract]
                                        implementation_factory=backend_processor_factory,
                                    )
                                    backend_processor = backend_processor_factory(
                                        service_provider
                                    )
                            except Exception:
                                # If we can't register factories, fall back to direct instantiation
                                from src.core.services.backend_processor import (
                                    BackendProcessor,
                                )
                                from src.core.services.command_processor import (
                                    CommandProcessor,
                                )

                                command_processor = CommandProcessor(concrete_cmd)
                                backend_processor = BackendProcessor(
                                    concrete_backend, concrete_session, app_state
                                )
                    # Ensure we have instances
                    if command_processor is None:
                        from src.core.services.command_processor import CommandProcessor

                        command_processor = CommandProcessor(concrete_cmd)
                    if backend_processor is None:
                        from src.core.services.backend_processor import BackendProcessor

                        backend_processor = BackendProcessor(
                            concrete_backend, concrete_session, app_state
                        )

                    # Get the new decomposed services
                    # Get session resolver from service provider
                    from src.core.interfaces.session_resolver_interface import (
                        ISessionResolver,
                    )
                    from src.core.services.backend_request_manager_service import (
                        BackendRequestManager,
                    )
                    from src.core.services.response_manager_service import (
                        ResponseManager,
                    )
                    from src.core.services.session_manager_service import SessionManager

                    session_resolver = service_provider.get_service(ISessionResolver)  # type: ignore[type-abstract]
                    if session_resolver is None:
                        from src.core.services.session_resolver_service import (
                            DefaultSessionResolver,
                        )

                        session_resolver = DefaultSessionResolver(None)  # type: ignore[arg-type]

                    # Get agent response formatter for ResponseManager
                    from src.core.interfaces.agent_response_formatter_interface import (
                        IAgentResponseFormatter,
                    )

                    agent_response_formatter = service_provider.get_service(IAgentResponseFormatter)  # type: ignore[type-abstract]
                    if agent_response_formatter is None:
                        from src.core.services.response_manager_service import (
                            AgentResponseFormatter,
                        )

                        agent_response_formatter = AgentResponseFormatter()

                    session_manager = SessionManager(concrete_session, session_resolver)

                    from src.core.interfaces.wire_capture_interface import (
                        IWireCapture,
                    )

                    wire_capture = service_provider.get_service(IWireCapture)  # type: ignore[type-abstract]

                    backend_request_manager = BackendRequestManager(
                        backend_processor,
                        concrete_response_proc,
                        wire_capture=wire_capture,
                    )
                    response_manager = ResponseManager(agent_response_formatter)

                    request_processor = RequestProcessor(
                        command_processor,
                        session_manager,
                        backend_request_manager,
                        response_manager,
                        app_state=app_state,
                    )

                # Register it for future use
                # Only try to register if the service provider is a ServiceProvider instance
                # that has the _singleton_instances attribute
                from src.core.di.container import ServiceProvider

                if isinstance(service_provider, ServiceProvider):
                    # Instead of mutating internal provider state, prefer registering
                    # the instance on the ServiceCollection so a rebuild would include it.
                    try:
                        from src.core.di.services import get_service_collection

                        services = get_service_collection()
                        # Register existing instance explicitly to ensure future resolutions
                        services.add_instance(IRequestProcessor, request_processor)  # type: ignore[type-abstract]
                        services.add_instance(RequestProcessor, request_processor)  # type: ignore[type-abstract]
                    except Exception:
                        # As a last resort, fall back to internal cache mutation
                        singleton_instances = getattr(
                            service_provider, "_singleton_instances", None
                        )
                        if singleton_instances is not None:
                            singleton_instances[IRequestProcessor] = request_processor
                            singleton_instances[RequestProcessor] = request_processor

        if request_processor is None:
            raise InitializationError("Could not find or create RequestProcessor")

        return ChatController(request_processor)
    except Exception as e:
        raise InitializationError(f"Failed to create ChatController: {e}") from e
