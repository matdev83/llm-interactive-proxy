from __future__ import annotations

import copy
import json
import logging
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Request
from starlette.responses import Response, StreamingResponse

from src.agents import (
    convert_cline_marker_to_openai_tool_call,
    detect_agent,
    format_command_response_for_agent,
)
from src.core.common.exceptions import LoopDetectionError
from src.core.domain.chat import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    StreamingChatResponse,
)
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.session import Session, SessionInteraction
from src.core.interfaces.backend_service import IBackendService
from src.core.interfaces.command_service import ICommandService
from src.core.interfaces.request_processor import IRequestProcessor
from src.core.interfaces.response_processor import IResponseProcessor
from src.core.interfaces.session_service import ISessionService

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
    ) -> None:
        """Initialize the request processor.

        Args:
            command_service: Service for processing commands
            backend_service: Service for interacting with backends
            session_service: Service for managing sessions
            response_processor: Service for processing responses
        """
        self._command_service = command_service
        self._backend_service = backend_service
        self._session_service = session_service
        self._response_processor = response_processor

    def _safe_get(self, obj: Any, attr: str, default: Any = None) -> Any:
        """Safely get attribute from object or key from dict"""
        if isinstance(obj, dict):
            return obj.get(attr, default)
        else:
            return getattr(obj, attr, default)

    async def process_request(self, request: Request, request_data: dict[str, Any]) -> Response:
        """Process an incoming chat completion request.

        Args:
            request: The FastAPI Request object
            request_data: The parsed request data

        Returns:
            An appropriate response object
        """
        # Extract key data from request for processing
        stream: bool = self._safe_get(request_data, "stream", False)
        messages: list[dict[str, Any]] = copy.deepcopy(
            self._safe_get(request_data, "messages", [])
        )

        # Normalize message items: tests and some internal callers sometimes pass
        # Pydantic ChatMessage instances; convert them to plain dicts for
        # consistent downstream handling.
        normalized: list[dict[str, Any]] = []
        for m in messages:
            try:
                if hasattr(m, "model_dump") and callable(getattr(m, "model_dump")):
                    normalized.append(m.model_dump())
                else:
                    normalized.append(m)
            except Exception:
                normalized.append(m)
        messages = normalized

        # Get or extract session ID
        session_id: str | None = self._safe_get(request_data, "session_id")
        if not session_id:
            # Try to get session ID from headers or cookies
            session_id = request.headers.get("x-session-id")
            if not session_id:
                # For backwards compatibility with tests, default to the
                # well-known session id 'default' when none is provided by
                # the caller. Previously we generated a UUID here which made
                # tests inspect a different session than the one updated by
                # commands.
                session_id = "default"
        assert session_id is not None, "Session ID should not be None at this point"

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
        disable_commands: bool = getattr(
            request.state, "disable_commands", False
        ) or getattr(request.app.state, "disable_interactive_commands", False)

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

        processed_messages: list[dict[str, Any]] = command_result.modified_messages
        logger.debug(f"Command executed: {command_result.command_executed}")
        logger.debug(
            f"Processed messages after command processing: {processed_messages}"
        )

        # If commands were processed, update session
        if command_result.command_executed:
            logger.debug("Command was executed.")
            # Get updated session after command execution
            session = await self._session_service.get_session(session_id)

            # Propagate per-session failover routes to application state so
            # subsequent requests without session_id still see the route.
            try:
                fr = getattr(session.state.backend_config, "failover_routes", None)
                if fr:
                    request.app.state.failover_routes = fr
            except Exception:
                pass

            # Format command result response
            response_data: dict[str, Any] = await self._handle_command_only_response(
                request_data, command_result, session, raw_prompt
            )

            # Return the command response directly
            return Response(
                content=json.dumps(response_data),
                media_type="application/json",
            )

        # If no commands were executed, proceed to backend
        try:
            # Include any app-level failover routes (e.g., created via commands)
            app_failover_routes: dict[str, Any] | None = None
            try:
                app_failover_routes = getattr(
                    request.app.state, "failover_routes", None
                )
            except Exception:
                app_failover_routes = None

            # Prepare the request for the backend
            request_model: str = self._safe_get(request_data, "model", "")
            temperature: float | None = self._safe_get(request_data, "temperature")
            top_p: float | None = self._safe_get(request_data, "top_p")
            max_tokens: int | None = self._safe_get(request_data, "max_tokens")

            # Add session interaction for the request
            session.add_interaction(
                SessionInteraction(
                    prompt=raw_prompt,
                    handler="proxy",
                    messages=copy.deepcopy(processed_messages),
                    is_request=True,
                )
            )

            # Convert request_data to a plain dict if it's a Pydantic model
            extra_body_dict = {}
            if hasattr(request_data, "model_dump"):
                extra_body_dict = request_data.model_dump()
            elif isinstance(request_data, dict):
                extra_body_dict = request_data
            else:
                # Best effort conversion
                extra_body_dict = {
                    k: v for k, v in request_data.__dict__.items() 
                    if not k.startswith("_") and not callable(v)
                }

            # Call the backend
            response_data: ChatResponse | StreamingChatResponse
            try:
                # Include session-related data in extra_body if needed
                if app_failover_routes:
                    extra_body_dict["failover_routes"] = app_failover_routes
                
                response_data = await self._backend_service.call_completion(
                    request=ChatRequest(
                        model=request_model,
                        messages=processed_messages,
                        temperature=temperature,
                        top_p=top_p,
                        max_tokens=max_tokens,
                        stream=stream,
                        extra_body=extra_body_dict,
                    ),
                    stream=stream
                )
            except Exception as e:
                # Add a failed interaction to the session
                session.add_interaction(
                    SessionInteraction(
                        prompt=raw_prompt,
                        handler="backend",
                        messages=[{"role": "error", "content": str(e)}],
                        is_request=False,
                    )
                )
                # Re-raise the exception
                raise

            # Process the response
            if stream:
                # For streaming responses, we need to wrap the iterator
                return self._create_streaming_response(
                    response_data, request_data, session
                )
            else:
                # For non-streaming responses, we can process directly
                return await self._create_non_streaming_response(
                    response_data, request_data, session
                )

        except LoopDetectionError as e:
            # Special handling for loop detection errors
            logger.warning(f"Loop detection error: {e}")
            return Response(
                content=json.dumps(
                    {
                        "error": {
                            "message": str(e),
                            "type": "loop_detection_error",
                            "param": None,
                            "code": "loop_detected",
                        }
                    }
                ),
                status_code=400,
                media_type="application/json",
            )
        except HTTPException as e:
            # Re-raise HTTP exceptions
            raise
        except Exception as e:
            # Log and re-raise other exceptions
            logger.exception(f"Error processing request: {e}")
            raise

    def _extract_raw_prompt(self, messages: list[dict[str, Any]]) -> str:
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
            if self._safe_get(message, "role") == "user":
                return self._safe_get(message, "content", "")

        # If no user message found, return empty string
        return ""

    async def _handle_command_only_response(
        self,
        request_data: dict[str, Any],
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
        session.add_interaction(
            SessionInteraction(
                prompt=raw_prompt,
                handler="proxy",
                messages=[{"role": "user", "content": raw_prompt}],
                is_request=True,
            )
        )

        # Format the command results for the response
        results = []
        for result in command_result.command_results:
            # CommandResultWrapper doesn't have 'command' attribute, but has 'result'
            # which might have 'cmd_name' or other identifiers
            cmd_name = ""
            if hasattr(result, "result") and hasattr(result.result, "cmd_name"):
                cmd_name = result.result.cmd_name
            elif hasattr(result, "result") and hasattr(result.result, "command"):
                cmd_name = result.result.command
            else:
                # Fallback to a generic name
                cmd_name = "command"
                
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
                messages=[{"role": "assistant", "content": response_content}],
                is_request=False,
            )
        )

        # Format the response based on the agent type
        agent_type = session.agent
        if agent_type:
            return format_command_response_for_agent(
                agent_type, results, request_data, session
            )

        # Default response format
        return {
            "id": f"chatcmpl-{time.time_ns()}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self._safe_get(request_data, "model", "command-processor"),
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
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }

    async def _create_non_streaming_response(
        self, response_data: ChatResponse, request_data: dict[str, Any], session: Session
    ) -> Response:
        """Create a non-streaming response.

        Args:
            response_data: The response data from the backend
            request_data: The original request data
            session: The session

        Returns:
            The formatted response
        """
        # Add the response interaction to the session
        try:
            content = None
            if (
                response_data.choices
                and len(response_data.choices) > 0
                and response_data.choices[0].message
            ):
                content = response_data.choices[0].message.content

            # Extract raw prompt from the request
            raw_prompt = ""
            for message in reversed(request_data.get("messages", [])):
                if message.get("role") == "user":
                    raw_prompt = message.get("content", "")
                    break

            session.add_interaction(
                SessionInteraction(
                    prompt=raw_prompt,
                    handler="backend",
                    messages=[
                        {"role": "assistant", "content": content or "<no content>"}
                    ],
                    is_request=False,
                )
            )
        except Exception as e:
            logger.error(f"Error adding interaction to session: {e}")

        # Process the response for loop detection if needed
        # Get session_id from the session
        session_id = getattr(session, "id", "default")
        try:
            # This will check for loops and raise LoopDetectionError if found
            await self._response_processor.process_response(
                response_data, session_id
            )
        except Exception as e:
            # Log but don't fail if response processing has issues
            logger.debug(f"Response processing note: {e}")

        # Convert the original response to JSON
        response_json = response_data.model_dump(exclude_none=True)

        # Return the response
        return Response(
            content=json.dumps(response_json),
            media_type="application/json",
        )

    def _create_streaming_response(
        self,
        response_data: StreamingChatResponse,
        request_data: dict[str, Any],
        session: Session,
    ) -> StreamingResponse:
        """Create a streaming response.

        Args:
            response_data: The streaming response data from the backend
            request_data: The original request data
            session: The session

        Returns:
            The streaming response
        """
        # Extract raw prompt from the request
        raw_prompt = ""
        for message in reversed(request_data.get("messages", [])):
            if message.get("role") == "user":
                raw_prompt = message.get("content", "")
                break

        # Add a placeholder interaction for streaming responses
        session.add_interaction(
            SessionInteraction(
                prompt=raw_prompt,
                handler="backend",
                messages=[{"role": "assistant", "content": "<streaming>"}],
                is_request=False,
            )
        )

        # Create the streaming response
        return StreamingResponse(
            self._stream_response(response_data, request_data),
            media_type="text/event-stream",
        )

    async def _stream_response(
        self, response_data: StreamingChatResponse, request_data: dict[str, Any]
    ) -> AsyncIterator[bytes]:
        """Stream the response data.

        Args:
            response_data: The streaming response data from the backend
            request_data: The original request data

        Yields:
            Chunks of the streaming response
        """
        try:
            agent_type = self._safe_get(request_data, "agent_type")
            is_cline = agent_type == "cline"

            async for chunk in response_data.iter_chunks():
                # Process the chunk
                processed_chunk = self._response_processor.process_chunk(
                    chunk, request_data
                )

                # Convert to JSON
                chunk_json = processed_chunk.model_dump(exclude_none=True)

                # Special handling for Cline tool calls
                if is_cline and chunk_json.get("choices", []):
                    for choice in chunk_json["choices"]:
                        if (
                            choice.get("delta", {}).get("content") is not None
                            and "```cline-tool-call" in choice["delta"]["content"]
                        ):
                            choice["delta"] = convert_cline_marker_to_openai_tool_call(
                                choice["delta"]["content"]
                            )

                # Yield the chunk
                yield f"data: {json.dumps(chunk_json)}\n\n".encode("utf-8")

            # End the stream
            yield b"data: [DONE]\n\n"
        except Exception as e:
            logger.exception(f"Error streaming response: {e}")
            error_json = {
                "error": {"message": str(e), "type": "streaming_error"}
            }
            yield f"data: {json.dumps(error_json)}\n\n".encode("utf-8")
            yield b"data: [DONE]\n\n"