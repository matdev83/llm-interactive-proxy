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
from src.core.domain.session import SessionInteraction
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
    ):
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

    async def process_request(self, request: Request, request_data: Any) -> Response:
        """Process an incoming chat completion request.

        Args:
            request: The FastAPI Request object
            request_data: The parsed request data

        Returns:
            An appropriate response object
        """

        # Extract key data from request for processing
        def safe_get(obj, attr, default=None):
            """Safely get attribute from object or key from dict"""
            if isinstance(obj, dict):
                return obj.get(attr, default)
            else:
                return getattr(obj, attr, default)

        stream = safe_get(request_data, "stream", False)
        messages = copy.deepcopy(safe_get(request_data, "messages", []))

        # Get or extract session ID
        session_id = safe_get(request_data, "session_id")
        if not session_id:
            # Try to get session ID from headers or cookies
            session_id = request.headers.get("x-session-id")
            if not session_id:
                # Generate a new session ID if not provided
                import uuid

                session_id = str(uuid.uuid4())

        logger.debug(f"Processing request for session {session_id}")
        logger.debug(f"Initial messages: {messages}")

        # Get the session
        session = await self._session_service.get_session(session_id)

        # Get raw prompt content
        raw_prompt = self._extract_raw_prompt(messages)

        # Check for agent type
        agent_type = detect_agent(raw_prompt)
        if agent_type:
            session.agent = agent_type
            logger.debug(f"Detected agent type: {agent_type}")

        # Process any commands in the messages (unless disabled)
        disable_commands = getattr(request.state, "disable_commands", False) or getattr(
            request.app.state, "disable_interactive_commands", False
        )

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

        processed_messages = command_result.modified_messages
        logger.debug(f"Command executed: {command_result.command_executed}")
        logger.debug(
            f"Processed messages after command processing: {processed_messages}"
        )

        # If commands were processed, update session
        if command_result.command_executed:
            logger.debug("Command was executed.")
            # Get updated session after command execution
            session = await self._session_service.get_session(session_id)

            # Handle command-only requests
            has_meaningful_content = await self._check_for_meaningful_content(
                processed_messages
            )
            logger.debug(f"Has meaningful content: {has_meaningful_content}")

            if not has_meaningful_content:
                logger.debug("Handling command-only response.")
                # Format command result response
                response_data = await self._handle_command_only_response(
                    request_data, command_result, session, raw_prompt
                )
                return Response(
                    content=json.dumps(response_data), media_type="application/json"
                )

        # If we get here, there's meaningful content to send to the backend

        # Check for project setting requirement
        if (
            hasattr(request, "app")
            and hasattr(request.app.state, "force_set_project")
            and request.app.state.force_set_project
            and not session.state.project
        ):
            raise HTTPException(
                status_code=400,
                detail="Project name not set. Use !/set(project=<n>) before sending prompts.",
            )

        # Convert request to our domain model
        chat_request = self._convert_to_domain_request(
            request_data, processed_messages, session
        )

        # Call the backend
        try:
            start_time = time.time()

            if stream:
                # Streaming response
                response_iterator = await self._backend_service.call_completion(
                    chat_request, stream=True
                )
                # Type assertion: when stream=True, call_completion returns AsyncIterator[StreamingChatResponse]
                from typing import cast

                streaming_response_iterator = cast(
                    AsyncIterator[StreamingChatResponse], response_iterator
                )

                # Record interaction in session before returning
                interaction = SessionInteraction(
                    prompt=raw_prompt,
                    handler="backend",
                    backend=chat_request.extra_body.get("backend_type"),
                    model=chat_request.model,
                    project=session.state.project,
                    parameters=chat_request.model_dump(exclude={"messages"}),
                )
                session.add_interaction(interaction)
                await self._session_service.update_session(session)

                # Use the response processor to process the stream
                processed_stream = self._response_processor.process_streaming_response(
                    streaming_response_iterator, session_id
                )

                # Return streaming response
                return StreamingResponse(
                    self._convert_processed_stream_to_sse(processed_stream, start_time),
                    media_type="text/event-stream",
                )
            else:
                # Non-streaming response
                response = await self._backend_service.call_completion(
                    chat_request, stream=False
                )
                # Type assertion: when stream=False, call_completion returns ChatResponse
                from typing import cast

                chat_response = cast(ChatResponse, response)

                # Record interaction in session
                interaction = SessionInteraction(
                    prompt=raw_prompt,
                    handler="backend",
                    backend=chat_request.extra_body.get("backend_type"),
                    model=chat_request.model,
                    project=session.state.project,
                    parameters=chat_request.model_dump(exclude={"messages"}),
                    response=self._extract_response_content(chat_response),
                    usage=self._extract_response_usage(chat_response),
                )
                session.add_interaction(interaction)
                await self._session_service.update_session(session)

                # Process the response using the response processor
                processed_response = await self._response_processor.process_response(
                    chat_response, session_id
                )

                # Convert the processed response back to a format suitable for HTTP response
                response_data = self._convert_processed_response_to_dict(
                    chat_response, processed_response
                )

                # Ensure OpenAI-compatible shape
                response_data.setdefault("object", "chat.completion")

                # Return the processed response
                return Response(
                    content=json.dumps(response_data), media_type="application/json"
                )

        except LoopDetectionError as e:
            logger.exception(f"Loop detection error: {e!s}")
            raise e  # Re-raise the specific LoopDetectionError
        except Exception as e:
            logger.exception(f"Error calling backend: {e!s}")
            raise HTTPException(status_code=500, detail=f"Error calling backend: {e!s}")

    def _extract_raw_prompt(self, messages: list[dict[str, Any]]) -> str:
        """Extract raw prompt from the messages.

        Args:
            messages: List of message objects

        Returns:
            The raw prompt text
        """
        if not messages:
            return ""

        # Find the last user message
        for message in reversed(messages):
            if message.get("role") == "user":
                content = message.get("content", "")
                if content and isinstance(content, str):
                    return content
                elif isinstance(content, list):
                    # Handle multipart content
                    texts = []
                    for part in content:
                        if part.get("type") == "text":
                            texts.append(part.get("text", ""))
                    return " ".join(texts)

        return ""

    async def _check_for_meaningful_content(
        self, messages: list[dict[str, Any]]
    ) -> bool:
        """Check if messages contain meaningful content beyond commands.

        Args:
            messages: List of message objects

        Returns:
            True if there is meaningful content
        """
        if not messages:
            return False

        # Check user messages for meaningful content
        for msg in messages:
            if msg.get("role") != "user":
                continue

            content = msg.get("content")
            if not content:
                continue

            if isinstance(content, str):
                # If the content starts with a command prefix, it's not meaningful content for backend processing
                if content.strip().startswith("!/"):
                    return False

                # Check if content has substance
                content = content.strip()

                # Skip very short content
                if len(content.split()) <= 2:  # 2 words or less
                    continue

                # Check for instruction indicators
                instruction_indicators = [
                    "write",
                    "create",
                    "generate",
                    "explain",
                    "describe",
                    "tell",
                    "show",
                    "help",
                    "how",
                    "what",
                    "why",
                    "where",
                    "when",
                    "please",
                    "can you",
                    "could you",
                    "would you",
                    "i need",
                    "i want",
                    "make",
                    "build",
                    "story",
                    "code",
                    "example",
                    "list",
                    "summary",
                    "analysis",
                ]

                content_lower = content.lower()
                has_instruction_words = any(
                    indicator in content_lower for indicator in instruction_indicators
                )

                # If it has instruction words and is substantial (>5 words), consider it meaningful
                if has_instruction_words and len(content.split()) > 5:
                    return True

            elif isinstance(content, list) and content:
                # Check if list has any non-empty text parts
                for part in content:
                    if part.get("type") == "text" and part.get("text", "").strip():
                        return True

        return False

    async def _handle_command_only_response(
        self, request_data: Any, command_result: Any, session: Any, raw_prompt: str
    ) -> dict[str, Any]:
        logger.debug("Inside _handle_command_only_response")
        """Format response for command-only requests.
        
        Args:
            request_data: The original request data
            command_result: Result of command processing
            session: The current session
            raw_prompt: The raw prompt text
            
        Returns:
            Formatted response object
        """
        # Build content lines for response
        content_lines = []

        # Add welcome banner if needed
        # TODO: Implement actual welcome banner handling

        # Add command result messages
        if command_result.command_results:
            confirmation_text = "\n".join(
                result.message for result in command_result.command_results
            )

            # For certain agents, filter out some messages
            if session.agent in {"cline", "roocode"}:
                # For Cline agents, include command results but exclude "hello acknowledged" confirmations
                if confirmation_text != "hello acknowledged":
                    content_lines.append(confirmation_text)
            else:
                # For non-Cline agents, include all confirmation messages
                content_lines.append(confirmation_text)

        final_content = "\n".join(content_lines)

        # Record the interaction
        interaction = SessionInteraction(
            prompt=raw_prompt,
            handler="proxy",
            model=request_data.model if hasattr(request_data, "model") else None,
            project=session.state.project,
            parameters={},  # Simplified for now
            response=final_content,
        )
        session.add_interaction(interaction)
        await self._session_service.update_session(session)

        # Format response based on agent type
        formatted_content = format_command_response_for_agent(
            [final_content], session.agent
        )

        # Handle Cline tool calls
        if session.agent in {"cline", "roocode"} and formatted_content.startswith(
            "__CLINE_TOOL_CALL_MARKER__"
        ):
            logger.debug("[CLINE_DEBUG] Converting Cline marker to OpenAI tool calls")

            # Convert marker to tool call
            tool_call = convert_cline_marker_to_openai_tool_call(formatted_content)

            return {
                "id": "proxy_cmd_processed",
                "object": "chat.completion",
                "created": int(datetime.now(timezone.utc).timestamp()),
                "model": (
                    request_data.model if hasattr(request_data, "model") else "unknown"
                ),
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": tool_call["id"],
                                    "type": tool_call["type"],
                                    "function": {
                                        "name": tool_call["function"]["name"],
                                        "arguments": tool_call["function"]["arguments"],
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            }
        else:
            # Regular content response (non-Cline or other frontends)
            return {
                "id": "proxy_cmd_processed",
                "object": "chat.completion",
                "created": int(datetime.now(timezone.utc).timestamp()),
                "model": (
                    request_data.model if hasattr(request_data, "model") else "unknown"
                ),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": formatted_content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            }

    def _convert_to_domain_request(
        self, request_data: Any, messages: list[dict[str, Any]], session: Any
    ) -> ChatRequest:
        """Convert API request to domain model.

        Args:
            request_data: The original request data
            messages: The processed messages
            session: The current session

        Returns:
            A ChatRequest domain object
        """
        # Convert messages to ChatMessage objects
        chat_messages = []
        for msg in messages:
            # Simple conversion for now
            chat_messages.append(
                ChatMessage(
                    role=msg.get("role", "user"),
                    content=msg.get("content"),
                    name=msg.get("name"),
                    tool_calls=msg.get("tool_calls"),
                    tool_call_id=msg.get("tool_call_id"),
                )
            )

        # Build a domain ChatRequest with appropriate properties
        extra_body = {}

        # Add backend type
        backend_type = session.state.backend_config.backend_type
        if backend_type:
            extra_body["backend_type"] = backend_type

        # Copy any other relevant request properties to extra_body
        # Handle both dict (legacy) and Pydantic model (new) request data
        if hasattr(request_data, "model_dump"):
            # New architecture: Pydantic model
            request_dict = request_data.model_dump(exclude_unset=True)
        else:
            # Legacy architecture: plain dict
            request_dict = request_data if isinstance(request_data, dict) else {}

        for key, value in request_dict.items():
            if key not in [
                "model",
                "messages",
                "stream",
                "temperature",
                "top_p",
                "n",
                "stop",
                "max_tokens",
                "presence_penalty",
                "frequency_penalty",
                "logit_bias",
                "tools",
                "tool_choice",
                "user",
                "session_id",
                "reasoning_effort",
                "reasoning",
                "thinking_budget",
                "generation_config",
            ]:
                extra_body[key] = value

        # Create the domain request using safe attribute/key access
        def safe_get(obj, attr, default=None):
            """Safely get attribute from object or key from dict"""
            if isinstance(obj, dict):
                return obj.get(attr, default)
            else:
                return getattr(obj, attr, default)

        return ChatRequest(
            messages=chat_messages,
            model=session.state.backend_config.model or safe_get(request_data, "model"),
            stream=safe_get(request_data, "stream", False),
            temperature=session.state.reasoning_config.temperature
            or safe_get(request_data, "temperature"),
            top_p=safe_get(request_data, "top_p"),
            n=safe_get(request_data, "n"),
            stop=safe_get(request_data, "stop"),
            max_tokens=safe_get(request_data, "max_tokens"),
            presence_penalty=safe_get(request_data, "presence_penalty"),
            frequency_penalty=safe_get(request_data, "frequency_penalty"),
            logit_bias=safe_get(request_data, "logit_bias"),
            tools=safe_get(request_data, "tools"),
            tool_choice=safe_get(request_data, "tool_choice"),
            user=safe_get(request_data, "user"),
            session_id=session.session_id,
            extra_body=extra_body,
            reasoning_effort=safe_get(request_data, "reasoning_effort"),
            reasoning=safe_get(request_data, "reasoning"),
            thinking_budget=safe_get(request_data, "thinking_budget"),
            generation_config=safe_get(request_data, "generation_config"),
        )

    async def _convert_processed_stream_to_sse(
        self, processed_stream: AsyncIterator[Any], start_time: float
    ) -> AsyncIterator[bytes]:
        """Convert processed streaming response to SSE format.

        Args:
            processed_stream: Iterator of processed responses
            start_time: When the request started

        Yields:
            Bytes for SSE streaming response
        """
        try:
            async for chunk in processed_stream:
                # Check for error in the processed response
                if chunk.metadata and "error" in chunk.metadata:
                    error_json = json.dumps(
                        {
                            "error": {
                                "message": chunk.content,
                                "type": chunk.metadata.get(
                                    "error_type", "stream_error"
                                ),
                                "details": chunk.metadata.get("error"),
                            }
                        }
                    )
                    yield f"data: {error_json}\n\n".encode()
                    continue

                # Create a response chunk with the processed content
                response_chunk = {
                    "object": "chat.completion.chunk",
                    "choices": [{"delta": {"content": chunk.content}, "index": 0}],
                }

                # Add any metadata (e.g., model, id, created)
                if chunk.metadata:
                    for key, value in chunk.metadata.items():
                        if key not in ["error", "error_type"]:
                            response_chunk[key] = value

                # Convert to SSE format
                chunk_json = json.dumps(response_chunk)
                yield f"data: {chunk_json}\n\n".encode()

        except Exception as e:
            # Handle streaming errors
            error_json = json.dumps(
                {
                    "error": {
                        "message": f"Error processing stream: {e!s}",
                        "type": "stream_error",
                    }
                }
            )
            yield f"data: {error_json}\n\n".encode()

        finally:
            # Send end of stream
            yield b"data: [DONE]\n\n"

            # Log completion time
            completion_time = time.time() - start_time
            logger.debug(f"Streaming request completed in {completion_time:.2f}s")

    def _convert_processed_response_to_dict(
        self, original_response: ChatResponse, processed_response: Any
    ) -> dict[str, Any]:
        """Convert a processed response to a dictionary for HTTP response.

        Args:
            original_response: The original response from the backend
            processed_response: The processed response from the response processor

        Returns:
            A dictionary suitable for HTTP response
        """
        # Start with the original response structure
        if isinstance(original_response, dict):
            response_data = dict(original_response)
        elif hasattr(original_response, "model_dump"):
            response_data = original_response.model_dump()
        elif hasattr(original_response, "dict"):
            response_data = original_response.dict()  # type: ignore[attr-defined]
        else:
            # Fallback - convert to dict using vars
            try:
                response_data = vars(original_response)
            except TypeError:
                response_data = {}

        # Check if there was an error in processing
        if processed_response.metadata and "error" in processed_response.metadata:
            # If there was an error, include it in the response
            response_data["error"] = {
                "message": processed_response.content,
                "type": processed_response.metadata.get("error", "processing_error"),
                "details": processed_response.metadata,
            }
            # We still return the original response with the error information
            return response_data

        # If the content was modified, update the response
        if processed_response.content and response_data["choices"]:
            # Update the content in the first choice
            choice = response_data["choices"][0]
            if isinstance(choice, dict) and "message" in choice:
                choice["message"]["content"] = processed_response.content

        # Add any additional metadata
        if processed_response.metadata:
            response_data["metadata"] = processed_response.metadata

        # Update usage information if available
        if processed_response.usage:
            response_data["usage"] = processed_response.usage

        return response_data

    def _extract_response_content(self, response: ChatResponse) -> str:
        """Extract content from a response.

        Args:
            response: The response object or dict

        Returns:
            The text content
        """
        # Handle dict responses (from tests/mocks)
        if isinstance(response, dict):
            choices = response.get("choices", [])
            if not choices:
                return ""
            choice = choices[0]
            if isinstance(choice, dict) and "message" in choice:
                message = choice["message"]
                if isinstance(message, dict) and "content" in message:
                    return message["content"] or ""
            return ""

        # Handle ChatResponse objects (from actual backend calls)
        if not response.choices:
            return ""

        choice = response.choices[0]
        if isinstance(choice, dict) and "message" in choice:
            message = choice["message"]
            if isinstance(message, dict) and "content" in message:
                return message["content"] or ""

        return ""

    def _extract_response_usage(self, response: ChatResponse) -> dict[str, Any] | None:
        """Extract usage information from a response.

        Args:
            response: The response object or dict

        Returns:
            The usage information as a dictionary, or None if not available
        """
        # Handle dict responses (from tests/mocks)
        if isinstance(response, dict):
            usage = response.get("usage")
            if isinstance(usage, dict):
                return usage
            return None

        # Handle ChatResponse objects (from actual backend calls)
        if not hasattr(response, "usage") or not response.usage:
            return None

        usage = response.usage
        # Try to extract usage as dict
        if hasattr(usage, "model_dump"):
            return usage.model_dump()  # type: ignore[attr-defined]
        elif hasattr(usage, "dict"):
            return usage.dict()  # type: ignore[attr-defined]
        elif isinstance(usage, dict):
            return usage
        else:
            # Convert to dict if it's an object with attributes
            try:
                return vars(usage)
            except TypeError:
                return None
