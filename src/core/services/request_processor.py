from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any, cast

from src.agents import (
    detect_agent,
    format_command_response_for_agent,
)
from src.core.common.exceptions import (
    LoopDetectionError,
)

# Import HTTP status constants
from src.core.constants import HTTP_400_BAD_REQUEST_MESSAGE
from src.core.domain.chat import (
    ChatCompletionChoice,
    ChatRequest,
    ChatResponse,
)
from src.core.domain.chat import ChatMessage as DomainChatMessage
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session import Session, SessionInteraction
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.command_service_interface import ICommandService
from src.core.interfaces.model_bases import DomainModel, InternalDTO
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.response_processor_interface import IResponseProcessor
from src.core.interfaces.session_resolver_interface import ISessionResolver
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.session_resolver_service import DefaultSessionResolver
from src.core.transport.fastapi.api_adapters import legacy_to_domain_chat_request

logger = logging.getLogger(__name__)


class RequestProcessor(IRequestProcessor):
    """Implementation of the request processor.

    This service orchestrates the request processing flow, including
    command handling, backend calls, and response processing.
    """

    def __init__(
        self,
        command_service: ICommandService,
        backend_service: IBackendService,
        session_service: ISessionService,
        response_processor: IResponseProcessor,
        session_resolver: ISessionResolver | None = None,
    ) -> None:
        """Initialize the request processor.

        Args:
            command_service: Service for processing commands
            backend_service: Service for interacting with backends
            session_service: Service for managing sessions
            response_processor: Service for processing responses
            session_resolver: Optional service for resolving session IDs
        """
        self._command_service = command_service
        self._backend_service = backend_service
        self._session_service = session_service
        self._response_processor = response_processor

        # Use provided session resolver or create a default one
        self._session_resolver = session_resolver or DefaultSessionResolver()

    async def process_request(
        self,
        context: RequestContext,
        request_data: DomainModel | InternalDTO | dict[str, Any],
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Process an incoming chat completion request.

        Args:
            context: Transport-agnostic request context containing headers/cookies/state
            request_data: The parsed request data

        Returns:
            An appropriate response object
        """
        # Convert legacy request to domain model if needed
        domain_request = request_data
        if not isinstance(request_data, ChatRequest):
            domain_request = legacy_to_domain_chat_request(request_data)
        else:
            # If it's already a ChatRequest, use it as is
            domain_request = request_data

        # Extract key data from request for processing
        stream: bool = (
            domain_request.stream if domain_request.stream is not None else False
        )
        logger.debug(
            f"domain_request.stream: {domain_request.stream}, Calculated stream: {stream}"
        )

        # Normalize message items: ensure all messages are DomainChatMessage objects for internal processing
        messages: list[DomainChatMessage] = [
            DomainChatMessage.model_validate(m) for m in domain_request.messages
        ]

        # Resolve session ID using the session resolver
        session_id: str = await self._session_resolver.resolve_session_id(context)

        logger.debug(f"Processing request for session {session_id}")
        logger.debug(f"Initial messages: {messages}")

        # Get the session
        session: Session = await self._session_service.get_session(session_id)

        # Get raw prompt content
        raw_prompt: str = self._extract_raw_prompt(messages)

        # Check for agent type
        agent_type: str | None = detect_agent(raw_prompt)
        if agent_type:
            session.agent = agent_type
            logger.debug(f"Detected agent type: {agent_type}")

        # Process any commands in the messages (unless disabled)
        # Command disabling flags are resolved from RequestContext.state and app_state
        # Use application state service instead of direct state access
        from src.core.services.application_state_service import (
            get_default_application_state,
        )
        
        app_state_service = get_default_application_state()
        disable_commands: bool = (
            getattr(context.state, "disable_commands", False) or
            app_state_service.get_disable_interactive_commands()
        )

        command_result: ProcessedResult

        if disable_commands:
            # Skip command processing
            from src.core.domain.processed_result import ProcessedResult

            command_result = ProcessedResult(
                command_executed=False, modified_messages=messages, command_results=[]
            )
        else:
            command_result = await self._command_service.process_commands(
                messages, session_id
            )
        logger.debug(
            f"command_result.command_executed: {command_result.command_executed}"
        )

        processed_messages = [m.to_dict() for m in command_result.modified_messages]
        logger.debug(f"Command executed: {command_result.command_executed}")
        logger.debug(
            f"Processed messages after command processing: {processed_messages}"
        )

        # Add this block
        if not processed_messages:
            logger.warning(
                "No messages after command processing, returning 400 Bad Request."
            )
            return ResponseEnvelope(
                content={
                    "error": {
                        "message": HTTP_400_BAD_REQUEST_MESSAGE,
                        "type": "invalid_request_error",
                        "param": "messages",
                        "code": "empty_messages",
                    }
                },
                status_code=400,
            )
        # End of new block

        # If commands were processed, update session
        if command_result.command_executed:
            logger.debug("Command was executed.")
            # Get updated session after command execution
            session = await self._session_service.get_session(session_id)

            # Propagate per-session failover routes to application state so
            # subsequent requests without session_id still see the route.
            from contextlib import suppress

            try:
                fr = getattr(session.state.backend_config, "failover_routes", None)
                if fr:
                    with suppress(Exception):
                        # Use application state service instead of direct state access
                        from src.core.services.application_state_service import (
                            get_default_application_state,
                        )
                        
                        app_state_service = get_default_application_state()
                        app_state_service.set_failover_routes(fr)
            except Exception:
                pass

            # Persisted session has been updated by CommandService. Decide whether
            # to return a command-only response or continue to backend. Some
            # commands (e.g., temperature/set) modify session state but still
            # expect the request to be forwarded to the backend. We use the
            # presence of 'data' on command results as a heuristic: if any
            # command result carries meaningful 'data' (like temperature), we
            # continue to call the backend; otherwise we return a command-only
            # response.
            logger.debug(
                f"command_result.command_results: {command_result.command_results}"
            )
            continue_to_backend = False
            for cr in command_result.command_results:
                try:
                    # CommandResultWrapper exposes .data
                    if getattr(cr, "data", None):
                        continue_to_backend = True
                        break
                except Exception:
                    continue

            logger.debug(f"continue_to_backend: {continue_to_backend}")
            if not continue_to_backend:
                # Format command result response
                response_data: dict[str, Any] = (
                    await self._handle_command_only_response(
                        domain_request, command_result, session, raw_prompt
                    )
                )

                # Return the command response as a domain envelope
                return ResponseEnvelope(
                    content=response_data,
                    status_code=200,
                )

        # If no commands were executed, proceed to backend
        try:
            # Include any app-level failover routes (e.g., created via commands)

            # Prepare the request for the backend
            request_model: str = (
                domain_request.model if domain_request.model is not None else ""
            )
            temperature: float | None = domain_request.temperature
            top_p: float | None = domain_request.top_p
            max_tokens: int | None = domain_request.max_tokens

            # Add session interaction for the request
            session.add_interaction(
                SessionInteraction(
                    prompt=raw_prompt,
                    handler="proxy",
                    backend=getattr(session.state.backend_config, "backend_type", None),
                    model=getattr(session.state.backend_config, "model", None),
                    project=getattr(session.state, "project", None),
                    parameters={
                        "temperature": temperature,
                        "top_p": top_p,
                        "max_tokens": max_tokens,
                    },
                )
            )

            # Convert request_data to a plain dict if it's a Pydantic model
            extra_body_dict: dict[str, Any] = {}
            if hasattr(request_data, "model_dump"):
                extra_body_dict = cast(dict[str, Any], request_data.model_dump())
            elif isinstance(request_data, dict):
                extra_body_dict = request_data
            else:
                # Best effort conversion
                extra_body_dict = {
                    k: v
                    for k, v in request_data.__dict__.items()
                    if not k.startswith("_") and not callable(v)
                }

            # Call the backend
            try:
                # Get failover routes from session and add them to extra_body
                failover_routes = getattr(
                    session.state.backend_config, "failover_routes", None
                )
                if failover_routes:
                    extra_body_dict["failover_routes"] = failover_routes

                backend_response_data: ResponseEnvelope | StreamingResponseEnvelope = (
                    await self._backend_service.call_completion(
                        request=ChatRequest(
                            model=request_model,
                            messages=[
                                DomainChatMessage.model_validate(msg)
                                for msg in processed_messages
                            ],
                            temperature=temperature,
                            top_p=top_p,
                            max_tokens=max_tokens,
                            stream=stream,
                            extra_body=extra_body_dict,
                        ),
                        stream=stream,
                    )
                )
            except Exception as e:
                # Add a failed interaction to the session
                session.add_interaction(
                    SessionInteraction(
                        prompt=raw_prompt,
                        handler="backend",
                        backend=getattr(
                            session.state.backend_config, "backend_type", None
                        ),
                        model=getattr(session.state.backend_config, "model", None),
                        project=getattr(session.state, "project", None),
                        response=str(e),
                    )
                )
                # Re-raise the exception
                raise

            # Process the response
            logger.debug(f"Stream flag: {stream}")

            # Handle various response types
            if isinstance(backend_response_data, ResponseEnvelope):
                # Return the envelope directly
                return backend_response_data
            elif isinstance(backend_response_data, StreamingResponseEnvelope):
                # Return the streaming envelope directly
                return backend_response_data
            elif stream:
                # For streaming responses coming from legacy backends, wrap the iterator
                return StreamingResponseEnvelope(
                    content=cast(AsyncIterator[bytes], backend_response_data),
                    media_type="text/event-stream",
                )
            else:
                # For non-streaming responses from legacy backends, process directly
                return ResponseEnvelope(
                    content=self._convert_to_dict(
                        cast(ChatResponse, backend_response_data)
                    ),
                    status_code=200,
                )

        except LoopDetectionError as e:
            # Special handling for loop detection errors
            logger.warning(f"Loop detection error: {e}")
            return ResponseEnvelope(
                content={
                    "error": {
                        "message": str(e),
                        "type": "loop_detection_error",
                        "code": "loop_detected",
                    }
                },
                status_code=400,
            )
        except Exception as e:
            # Log and re-raise other exceptions
            logger.exception(f"Error processing request: {e}")
            raise

    def _extract_raw_prompt(self, messages: list[DomainChatMessage]) -> Any:
        """Extract the raw prompt from a list of messages.

        Args:
            messages: The list of messages

        Returns:
            The raw prompt text
        """
        if not messages:
            return ""

        # Get the last user message
        for message in reversed(messages):
            if message.role == "user":
                content_value: Any = message.content  # Explicitly type as Any
                if isinstance(content_value, str):
                    return content_value
                elif isinstance(content_value, list):
                    # Handle multimodal content by converting to string
                    converted_content: str = self._convert_content_to_str(
                        cast(list[Any], content_value)
                    )
                    return converted_content
                elif content_value is None:
                    return ""  # Explicitly handle None
                else:
                    logger.warning(
                        f"Unexpected content type in _extract_raw_prompt: {type(content_value)}"
                    )
                    return str(
                        content_value
                    )  # Fallback for unexpected types, ensure string

        # If no user message found, return empty string
        return ""

    def _convert_to_dict(self, obj: Any) -> dict[str, Any]:
        """Convert an object to a dictionary.

        Args:
            obj: The object to convert

        Returns:
            A dictionary representation of the object
        """
        if isinstance(obj, dict):
            return obj
        elif hasattr(obj, "model_dump"):
            # Handle pydantic models
            return cast(dict[str, Any], obj.model_dump(exclude_none=True))
        else:
            # Generic fallback for other types
            result: dict[str, Any] = {
                "id": str(getattr(obj, "id", f"chatcmpl-{time.time_ns()}")),
                "object": str(getattr(obj, "object", "chat.completion")),
                "created": int(getattr(obj, "created", int(time.time()))),
                "model": str(getattr(obj, "model", "unknown")),
                "choices": list(getattr(obj, "choices", [])),
                "usage": dict(getattr(obj, "usage", {})),
            }

            # Ensure the object field is present
            if "object" not in result:
                result["object"] = "chat.completion"

            return result

    def _extract_response_content(self, response: Any) -> Any:
        """Extract content from a response object.

        Args:
            response: The response object (ChatResponse, dict, or other)

        Returns:
            The extracted content string

        Raises:
            AttributeError: If response is not a valid format
            TypeError: If response is not a valid type
        """
        # Handle ChatResponse object
        choices: list[Any]
        if hasattr(response, "choices"):
            choices = cast(list[Any], response.choices)
        elif isinstance(response, dict) and "choices" in response:
            choices = cast(list[Any], cast(dict, response)["choices"])
        else:
            # Handle tuple or other invalid types
            raise AttributeError(f"Response does not have 'choices': {type(response)}")

        # Ensure choices is a list before proceeding
        if not isinstance(choices, list):
            raise TypeError(f"Expected 'choices' to be a list, but got {type(choices)}")

        # Extract content from first choice
        if len(choices) > 0:
            choice = choices[0]
            if isinstance(choice, dict):  # This branch handles dict choices
                message = cast(dict, choice).get(
                    "content", ""
                )  # Directly cast and get content
                if isinstance(message, str):  # Add this check
                    return message
                else:
                    logger.warning(
                        f"Unexpected message content type in _extract_response_content: {type(message)}"
                    )
                    return ""
            elif isinstance(
                choice, ChatCompletionChoice
            ):  # This branch handles ChatCompletionChoice
                if choice.message:
                    return choice.message.content or ""
            else:
                # Fallback for unexpected types
                logger.warning(
                    f"Unexpected choice type in _extract_response_content: {type(choice)}"
                )
                return ""

    def _convert_content_to_str(self, content_parts: list[Any]) -> str:
        """Converts a list of content parts to a single string."""
        text_content = []
        for part in content_parts:
            if isinstance(part, dict) and part.get("type") == "text":
                text_content.append(part.get("text", ""))
            elif isinstance(part, str):
                text_content.append(part)
            else:
                text_content.append(cast(str, str(part)))  # Fallback for other types
        return "".join(text_content)

    async def _handle_command_only_response(
        self,
        request_data: ChatRequest,
        command_result: ProcessedResult,
        session: Session,
        raw_prompt: str,
    ) -> dict[str, Any]:
        """Handle a response when only commands were processed.

        Args:
            request_data: The original request data
            command_result: The result of command processing
            session: The session
            raw_prompt: The raw prompt text

        Returns:
            The formatted response data
        """
        # Add the command interaction to the session
        session.add_interaction(SessionInteraction(prompt=raw_prompt, handler="proxy"))

        # Format the command results for the response
        results = []
        for result in command_result.command_results:
            # CommandResultWrapper doesn't have 'command' attribute, but has 'result'
            # which might have 'cmd_name' or other identifiers
            cmd_name = (
                result.command
            )  # Directly use the 'command' property from CommandResultWrapper

            results.append(
                {
                    "command": cmd_name,
                    "success": result.success,
                    "message": result.message or "",
                }
            )

        # Add the response interaction to the session
        response_content = f"Commands executed: {len(results)}"
        session.add_interaction(
            SessionInteraction(
                prompt=raw_prompt,
                handler="proxy",
                backend=getattr(session.state.backend_config, "backend_type", None),
                model=getattr(session.state.backend_config, "model", None),
                project=getattr(session.state, "project", None),
                response=response_content,
            )
        )

        # Format the response based on the agent type
        agent_type = session.agent

        # Default response format - use proxy_cmd_processed for compatibility with tests
        response_dict: dict[str, Any] = {
            "id": "proxy_cmd_processed",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": (
                request_data.model
                if request_data.model is not None
                else "command-processor"
            ),
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "\n".join(
                            [f"{r['command']}: {r['message']}" for r in results]
                        ),
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

        if agent_type:
            formatted_content = format_command_response_for_agent(
                [f"{r['command']}: {r['message']}" for r in results], agent_type
            )
            # Ensure the nested structure exists before assigning
            if (
                response_dict.get("choices")
                and "message" in response_dict["choices"][0]
            ):
                response_dict["choices"][0]["message"]["content"] = formatted_content

        return response_dict
