"""
Tool-call retry coordinator service.

This service centralizes tool-call retry flow with escalating steering and enforces
retry limits to prevent infinite loops when LLMs repeatedly attempt dangerous commands.

Requirements: 3.5, 3.6, 3.7, 4.3, 6.1, 6.2, 6.3, 7.1, 9.1, 9.2, 10.1
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from src.core.domain.backend_request_manager.context_models import ToolCallRetryState
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.backend_request_manager_components import (
    IToolCallRetryCoordinator,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse

logger = logging.getLogger(__name__)


class ToolCallRetryCoordinator(IToolCallRetryCoordinator):
    """Coordinates tool-call retry flows with escalating steering."""

    # Tool-call swallow retry loop prevention (Escalating + Hard Limit)
    _MAX_DANGEROUS_COMMAND_RETRIES = 3
    _DANGEROUS_RETRY_KEY = "_tool_call_reactor_retry_count"
    _LEGACY_DANGEROUS_RETRY_KEY = "_dangerous_command_retry_count"

    _DEFAULT_BACKEND_STEERING_MESSAGE = (
        "A tool call was blocked by proxy policy. Do not repeat the blocked tool call. "
        "Respond to the user with a compliant approach that does not require tools."
    )

    # Escalating steering messages for each retry attempt
    _DANGEROUS_STEERING_MESSAGES: tuple[str, ...] = (
        # Retry 1: Standard steering
        (
            "[Proxy Steering Notice - First Warning]\n"
            "A tool call was blocked by proxy policy. You must comply with the steering "
            "instruction provided and respond to the user without repeating the blocked "
            "tool call.\n\n"
            "If the user still needs the blocked action, explain what they can do manually "
            "and continue with a safe alternative plan."
        ),
        # Retry 2: Stronger warning
        (
            "[Proxy Steering Notice - SECOND WARNING]\n"
            "STOP: You have repeated a blocked tool call. This will continue to be blocked.\n\n"
            "Do NOT attempt the blocked tool call again. Follow the steering instruction, "
            "tell the user what they can do manually (if needed), and proceed without tools."
        ),
        # Retry 3: Final warning before termination
        (
            "[Proxy Steering Notice - FINAL WARNING]\n"
            "CRITICAL: This is your THIRD blocked tool call attempt. If you attempt another "
            "blocked tool call, this interaction will be terminated.\n\n"
            "You MUST now:\n"
            "1. Acknowledge you cannot perform the blocked tool call\n"
            "2. Provide the user a safe manual alternative (if required)\n"
            "3. Continue with a compliant approach"
        ),
    )

    _DANGEROUS_TERMINAL_ERROR = (
        "[Proxy Steering - Session Terminated]\n\n"
        "This session has been terminated due to repeated attempts to perform blocked "
        "tool calls despite multiple warnings.\n\n"
        "The AI assistant attempted blocked tool calls {count} times. Each attempt was "
        "blocked by the proxy policy.\n\n"
        "Please start a new session to continue."
    )

    def __init__(self, backend_processor: IBackendProcessor) -> None:
        """Initialize the tool-call retry coordinator.

        Args:
            backend_processor: Backend processor for executing retry requests
        """
        self._backend_processor = backend_processor

    def _extract_session_id(self, context: RequestContext) -> str:
        """Extract session ID from request context.

        Args:
            context: Request context

        Returns:
            Session ID string
        """
        # Try context.session_id first
        if context.session_id:
            return context.session_id

        # Try processing_context.values.session_id
        if context.processing_context and isinstance(
            context.processing_context.values, dict
        ):
            session_id = context.processing_context.values.get("session_id")
            if isinstance(session_id, str) and session_id:
                return session_id

        # Fallback to request_id if available
        if context.request_id:
            return context.request_id

        # Ultimate fallback (should not happen in practice)
        return "unknown-session"

    def _should_retry(
        self, request: ChatRequest, retry_state: ToolCallRetryState
    ) -> bool:
        """Check if retry should be performed.

        Args:
            request: The backend request
            retry_state: Current retry state

        Returns:
            True if retry should be performed, False otherwise
        """
        # Guard against retry loops: if request is already marked as retry, don't retry again
        extra_body = request.extra_body or {}
        # Check if response indicates swallowed tool call (caller should check this)
        # This method just checks if retry is allowed based on request state
        return extra_body.get("_tool_call_reactor_retry") is not True

    def _extract_retry_count(self, request: ChatRequest) -> int:
        """Extract current retry count from request.

        Args:
            request: The backend request

        Returns:
            Current retry count
        """
        extra_body = request.extra_body or {}
        current_retry_count: int = extra_body.get(self._DANGEROUS_RETRY_KEY, 0)
        if not isinstance(current_retry_count, int):
            current_retry_count = 0

        # Check legacy alias and use higher value
        legacy_count = extra_body.get(self._LEGACY_DANGEROUS_RETRY_KEY, 0)
        if isinstance(legacy_count, int) and legacy_count > current_retry_count:
            current_retry_count = legacy_count

        return current_retry_count

    def _build_steering_message(
        self,
        metadata: dict[str, Any],
        retry_count: int,
        steering_message: str,
    ) -> str:
        """Build steering message with escalating warnings.

        Args:
            metadata: Response metadata containing swallowed tool call info
            retry_count: Current retry attempt count
            steering_message: Base steering message from metadata

        Returns:
            Complete steering prompt
        """
        swallowed_calls = metadata.get("swallowed_tool_calls")
        original_content = metadata.get("swallowed_original_content")

        # Build detailed summary of what was blocked
        summary_parts: list[str] = []
        if isinstance(original_content, str) and original_content.strip():
            summary_parts.append(original_content.strip())

        if isinstance(swallowed_calls, list) and swallowed_calls:
            descriptions: list[str] = []
            for raw_call in swallowed_calls:
                if not isinstance(raw_call, dict):
                    continue
                function_payload = raw_call.get("function")
                name = None
                if isinstance(function_payload, dict):
                    name = function_payload.get("name")
                if not name:
                    name = raw_call.get("type", "function")
                arguments = None
                if isinstance(function_payload, dict):
                    arguments = function_payload.get("arguments")
                arg_summary = ""
                if arguments is not None:
                    try:
                        arg_summary = json.dumps(arguments, ensure_ascii=False)
                    except Exception:
                        arg_summary = str(arguments)
                descriptions.append(f"name={name} arguments={arg_summary}".strip())
            if descriptions:
                summary_parts.append(
                    "Blocked tool call details:\n" + "\n".join(descriptions)
                )

        if not summary_parts:
            summary_parts.append(
                "A previous assistant response attempted a tool call that was blocked by the proxy."
            )

        steering_block = (
            "Steering instruction (must follow exactly):\n" + steering_message.strip()
        )

        # Select escalating steering message
        escalating_index = min(
            retry_count - 1, len(self._DANGEROUS_STEERING_MESSAGES) - 1
        )
        escalating_steering = self._DANGEROUS_STEERING_MESSAGES[escalating_index]

        proxy_prompt = (
            f"[Proxy Notice - Attempt {retry_count}/{self._MAX_DANGEROUS_COMMAND_RETRIES}]\n"
            + "\n\n".join(summary_parts)
            + "\n\n"
            + steering_block
            + "\n\n"
            + escalating_steering
        )

        return proxy_prompt

    def _create_terminal_response(
        self,
        retry_count: int,
        session_id: str,
        is_streaming: bool,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Create a terminal error response when retry limit is exceeded.

        Args:
            retry_count: Current retry count
            session_id: Session identifier
            is_streaming: Whether this is for a streaming request

        Returns:
            Terminal response envelope
        """
        terminal_content = self._DANGEROUS_TERMINAL_ERROR.format(count=retry_count)
        terminal_metadata = {
            "dangerous_command_limit_exceeded": True,
            "dangerous_command_retry_count": retry_count,
            "tool_call_reactor_retry_count": retry_count,
            "session_terminated": True,
            "is_done": True,
            "finish_reason": "security_limit",
            "session_id": session_id,
        }

        if is_streaming:

            async def _terminal_stream() -> AsyncIterator[ProcessedResponse]:
                yield ProcessedResponse(
                    content=terminal_content, metadata=terminal_metadata
                )

            return StreamingResponseEnvelope(
                content=_terminal_stream(), metadata=terminal_metadata
            )

        return ResponseEnvelope(content=terminal_content, metadata=terminal_metadata)

    async def handle_non_streaming(
        self,
        request: ChatRequest,
        response: ResponseEnvelope,
        context: RequestContext,
        retry_state: ToolCallRetryState,
    ) -> ResponseEnvelope | None:
        """Return a retried response or None when no retry is needed.

        Args:
            request: The original backend request
            response: The backend response indicating a swallowed tool call
            context: Request context
            retry_state: Current retry state tracking

        Returns:
            A retried response envelope, or None if no retry is needed
        """
        # Check if response indicates swallowed tool call
        metadata = response.metadata or {}
        if not metadata.get("tool_call_swallowed"):
            return None

        session_id = self._extract_session_id(context)

        # Extract current retry count from request
        current_retry_count = self._extract_retry_count(request)
        new_retry_count = current_retry_count + 1

        # Check if we've exceeded the maximum retry limit BEFORE checking if retry is allowed
        # This ensures terminal responses are returned even for retry requests
        if new_retry_count > self._MAX_DANGEROUS_COMMAND_RETRIES:
            logger.warning(
                "Tool call retry limit exceeded for session %s: "
                "%d attempts blocked. Terminating with error.",
                session_id,
                new_retry_count,
            )
            return self._create_terminal_response(
                retry_count=new_retry_count,
                session_id=session_id,
                is_streaming=False,
            )

        # Guard against retry loops (only check after limit check)
        should_retry = self._should_retry(request, retry_state)
        if not should_retry:
            return None

        # Extract steering message from metadata
        steering_message = metadata.get("steering_message")
        if not isinstance(steering_message, str) or not steering_message.strip():
            steering_message = self._DEFAULT_BACKEND_STEERING_MESSAGE

        # Build steering prompt
        proxy_prompt = self._build_steering_message(
            metadata=metadata,
            retry_count=new_retry_count,
            steering_message=steering_message,
        )

        # Update retry count for the next request
        extra_body = dict(request.extra_body or {})
        extra_body[self._DANGEROUS_RETRY_KEY] = new_retry_count
        extra_body[self._LEGACY_DANGEROUS_RETRY_KEY] = new_retry_count
        extra_body["_tool_call_reactor_retry"] = True

        # Create system message to append (preserves all original messages)
        system_message = ChatMessage(role="system", content=proxy_prompt)
        new_messages = [*list(request.messages), system_message]

        retry_request = request.model_copy(
            update={"messages": new_messages, "extra_body": extra_body}
        )

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Tool call blocked for session %s (attempt %d/%d), applying escalating steering",
                session_id,
                new_retry_count,
                self._MAX_DANGEROUS_COMMAND_RETRIES,
            )

        # Execute retry request
        try:
            retry_response = await self._backend_processor.process_backend_request(
                request=retry_request, session_id=session_id, context=context
            )

            # Return raw backend response (no middleware processing)
            if isinstance(retry_response, ResponseEnvelope):
                return retry_response
            # If streaming was returned for non-streaming request, convert to non-streaming
            # This shouldn't happen in practice, but handle gracefully
            if isinstance(retry_response, StreamingResponseEnvelope):
                # Extract first chunk as fallback
                async def _extract_content() -> str:
                    async for chunk in retry_response.content:
                        if hasattr(chunk, "content"):
                            return str(chunk.content)
                    return ""

                content = await _extract_content()
                return ResponseEnvelope(
                    content=content, metadata=retry_response.metadata or {}
                )

            return retry_response

        except Exception as exc:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Tool call reactor retry failed for session %s: %s",
                    session_id,
                    exc,
                    exc_info=True,
                )
            fallback_metadata = dict(metadata)
            fallback_metadata["tool_call_reactor_retry_failed"] = True
            fallback_metadata["steering_retry_occurred"] = True
            fallback_metadata["dangerous_command_retry_count"] = new_retry_count
            fallback_metadata["tool_call_reactor_retry_count"] = new_retry_count
            fallback_metadata["session_id"] = (
                session_id  # Req 9.2: Include session_id in retry metadata
            )
            fallback_content = (
                "[Proxy Notice]\n"
                "A tool call was blocked by proxy policy and the proxy attempted to recover, "
                "but the backend retry failed. Please retry your request."
            )
            return ResponseEnvelope(
                content=fallback_content, metadata=fallback_metadata
            )

    async def handle_streaming(
        self,
        request: ChatRequest,
        response: ResponseEnvelope,
        context: RequestContext,
        retry_state: ToolCallRetryState,
    ) -> StreamingResponseEnvelope | None:
        """Return a retried stream or terminal stream when needed.

        Args:
            request: The original backend request
            response: The backend response indicating a swallowed tool call
            context: Request context
            retry_state: Current retry state tracking

        Returns:
            A retried streaming response envelope, or None if no retry is needed
        """
        # Check if response indicates swallowed tool call
        metadata = response.metadata or {}
        if not metadata.get("tool_call_swallowed"):
            return None

        session_id = self._extract_session_id(context)

        # Extract current retry count from request
        current_retry_count = self._extract_retry_count(request)
        new_retry_count = current_retry_count + 1

        # Check if we've exceeded the maximum retry limit BEFORE checking if retry is allowed
        # This ensures terminal responses are returned even for retry requests
        if new_retry_count > self._MAX_DANGEROUS_COMMAND_RETRIES:
            logger.warning(
                "Tool call retry limit exceeded for session %s: "
                "%d attempts blocked. Terminating with error.",
                session_id,
                new_retry_count,
            )
            return self._create_terminal_response(
                retry_count=new_retry_count,
                session_id=session_id,
                is_streaming=True,
            )

        # Guard against retry loops (only check after limit check)
        if not self._should_retry(request, retry_state):
            return None

        # Extract steering message from metadata
        steering_message = metadata.get("steering_message")
        if not isinstance(steering_message, str) or not steering_message.strip():
            steering_message = self._DEFAULT_BACKEND_STEERING_MESSAGE

        # Build steering prompt
        proxy_prompt = self._build_steering_message(
            metadata=metadata,
            retry_count=new_retry_count,
            steering_message=steering_message,
        )

        # Update retry count for the next request
        extra_body = dict(request.extra_body or {})
        extra_body[self._DANGEROUS_RETRY_KEY] = new_retry_count
        extra_body[self._LEGACY_DANGEROUS_RETRY_KEY] = new_retry_count
        extra_body["_tool_call_reactor_retry"] = True

        # Create system message to append (preserves all original messages)
        system_message = ChatMessage(role="system", content=proxy_prompt)
        new_messages = [*list(request.messages), system_message]

        retry_request = request.model_copy(
            update={"messages": new_messages, "extra_body": extra_body}
        )

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Tool call blocked for session %s (attempt %d/%d), applying escalating steering",
                session_id,
                new_retry_count,
                self._MAX_DANGEROUS_COMMAND_RETRIES,
            )

        # Execute retry request
        try:
            retry_response = await self._backend_processor.process_backend_request(
                request=retry_request, session_id=session_id, context=context
            )

            # Return raw backend response (no middleware processing)
            if isinstance(retry_response, StreamingResponseEnvelope):
                return retry_response
            # If non-streaming was returned for streaming request, wrap it
            if isinstance(retry_response, ResponseEnvelope):

                async def _wrap_stream() -> AsyncIterator[ProcessedResponse]:
                    yield ProcessedResponse(
                        content=retry_response.content,
                        metadata=retry_response.metadata or {},
                    )

                return StreamingResponseEnvelope(
                    content=_wrap_stream(), metadata=retry_response.metadata or {}
                )

            return retry_response

        except Exception as exc:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Tool call reactor retry failed for session %s: %s",
                    session_id,
                    exc,
                    exc_info=True,
                )
            fallback_metadata = dict(metadata)
            fallback_metadata["tool_call_reactor_retry_failed"] = True
            fallback_metadata["steering_retry_occurred"] = True
            fallback_metadata["dangerous_command_retry_count"] = new_retry_count
            fallback_metadata["tool_call_reactor_retry_count"] = new_retry_count
            fallback_metadata["session_id"] = (
                session_id  # Req 9.2: Include session_id in retry metadata
            )
            # Preserve _steering_replacement if present in original response
            # This marker is needed for streaming accumulation reset
            if metadata.get("_steering_replacement"):
                fallback_metadata["_steering_replacement"] = True

            async def _fallback_stream() -> AsyncIterator[ProcessedResponse]:
                yield ProcessedResponse(
                    content=(
                        "[Proxy Notice]\n"
                        "A tool call was blocked by proxy policy and the proxy attempted to recover, "
                        "but the backend retry failed. Please retry your request."
                    ),
                    metadata=fallback_metadata,
                )

            return StreamingResponseEnvelope(
                content=_fallback_stream(), metadata=fallback_metadata
            )
