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

from pydantic.types import JsonValue

from src.core.domain.backend_request_manager.context_models import ToolCallRetryState
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.backend_request_manager_components import (
    IToolCallRetryCoordinator,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.session_cancellation_coordinator_interface import (
    ISessionCancellationCoordinator,
)
from src.core.transport.session_key_resolver import (
    resolve_session_key_from_request_context,
)

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

    def __init__(
        self,
        backend_processor: IBackendProcessor,
        cancellation_coordinator: ISessionCancellationCoordinator | None = None,
    ) -> None:
        """Initialize the tool-call retry coordinator.

        Args:
            backend_processor: Backend processor for executing retry requests
            cancellation_coordinator: Optional cancellation coordinator for checking session cancellation
        """
        self._backend_processor = backend_processor
        self._cancellation_coordinator = cancellation_coordinator

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

        Prevents infinite retry loops by checking the retry count against the max limit.
        The retry flow relies on monotonically increasing retry counters and a strict max retry limit.

        If request is already marked as retry but has no retry_count set (retry_count=0),
        don't retry again to prevent loops. This handles edge cases where a request is
        marked as retry but doesn't have proper retry tracking.

        Args:
            request: The backend request
            retry_state: Current retry state containing max_retries

        Returns:
            True if a retry should be performed, False if retry count is at or above limit.
        """
        extra_body = request.extra_body or {}
        current_retry_count = self._extract_retry_count(request)

        # If request is already marked as retry but has no retry_count set, don't retry
        # This prevents loops when a request is marked as retry but doesn't have proper tracking
        # Check for both True and truthy values to handle edge cases where marker might be set to 1 or other truthy values
        retry_marker = extra_body.get("_tool_call_reactor_retry")
        if (
            retry_marker is True or (retry_marker is not False and bool(retry_marker))
        ) and current_retry_count == 0:
            return False

        # Allow retries as long as we're below the limit (not at or above)
        # When current_retry_count reaches max_retries, we've used all retries
        return current_retry_count < retry_state.max_retries

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
        terminal_metadata: dict[str, JsonValue] = {
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

    def _attach_retry_metadata(
        self,
        *,
        metadata: dict[str, Any],
        retry_count: int,
        session_id: str,
    ) -> dict[str, Any]:
        """Ensure retry-related metadata is preserved on the response.

        The backend retry response often has empty metadata, but callers/tests
        expect retry counters and flags to be present on the returned envelope.
        """
        merged = dict(metadata or {})
        merged.setdefault("steering_retry_occurred", True)
        merged.setdefault("dangerous_command_retry_count", retry_count)
        merged.setdefault("tool_call_reactor_retry_count", retry_count)
        merged.setdefault("session_id", session_id)
        return merged

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
        # IMPORTANT: Only read from request.extra_body, never from retry_state.retry_count
        # retry_state.retry_count is for tracking state, not for calculating new retry count
        current_retry_count = self._extract_retry_count(request)
        # Retry count represents the retry attempt number (1-indexed)
        # For the first retry (when count is 0, meaning first attempt), set it to 1 (first retry)
        # For subsequent retries, increment the existing count
        if current_retry_count == 0:
            new_retry_count = 1  # First retry
        else:
            new_retry_count = current_retry_count + 1

        # Check if we've exceeded the maximum retry limit first
        # This ensures terminal responses are returned even for retry requests
        # When retry_count > MAX, we've exceeded the limit and should stop
        # MAX_DANGEROUS_COMMAND_RETRIES=3 means we allow retry_count values 1, 2, 3
        limit_exceeded = new_retry_count > self._MAX_DANGEROUS_COMMAND_RETRIES

        # If limit exceeded, return terminal response (don't check _should_retry)
        if limit_exceeded:
            logger.warning(
                "Tool call retry limit exceeded for session %s: "
                "%d attempts blocked. Terminating with error.",
                session_id,
                new_retry_count,
            )
            terminal_response = self._create_terminal_response(
                retry_count=new_retry_count,
                session_id=session_id,
                is_streaming=False,
            )
            # Type narrowing: _create_terminal_response returns ResponseEnvelope when is_streaming=False
            assert isinstance(terminal_response, ResponseEnvelope)
            return terminal_response

        # Check if we should retry (handles edge cases like requests marked as retry but without retry_count)
        # Only check this after limit check, so we can return terminal responses when limit is exceeded
        if not self._should_retry(request, retry_state):
            return None

        # Guard against retry loops - check if new_retry_count would exceed the limit
        if new_retry_count > retry_state.max_retries:
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

        # Cancellation gate: ensure session is not cancelled before tool call retry
        session_key = resolve_session_key_from_request_context(context)
        if self._cancellation_coordinator is not None and session_key is not None:
            self._cancellation_coordinator.ensure_not_cancelled(session_key)

        # Execute retry request
        try:
            retry_response = await self._backend_processor.process_backend_request(
                request=retry_request, session_id=session_id, context=context
            )

            # Return raw backend response (no middleware processing)
            if isinstance(retry_response, ResponseEnvelope):
                retry_response.metadata = self._attach_retry_metadata(
                    metadata=retry_response.metadata or {},
                    retry_count=new_retry_count,
                    session_id=session_id,
                )
                return retry_response
            # If streaming was returned for non-streaming request, convert to non-streaming
            # This shouldn't happen in practice, but handle gracefully
            if isinstance(retry_response, StreamingResponseEnvelope):
                # Extract first chunk as fallback
                async def _extract_content() -> str:
                    if retry_response.content is not None:
                        async for chunk in retry_response.content:
                            if hasattr(chunk, "content"):
                                return str(chunk.content)
                    return ""

                content = await _extract_content()
                converted_md = self._attach_retry_metadata(
                    metadata=retry_response.metadata or {},
                    retry_count=new_retry_count,
                    session_id=session_id,
                )
                return ResponseEnvelope(content=content, metadata=converted_md)

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
        # IMPORTANT: Only read from request.extra_body, never from retry_state.retry_count
        # retry_state.retry_count is for tracking state, not for calculating new retry count
        current_retry_count = self._extract_retry_count(request)
        # Retry count represents the retry attempt number (1-indexed)
        # For the first retry (when count is 0, meaning first attempt), set it to 1 (first retry)
        # For subsequent retries, increment the existing count
        if current_retry_count == 0:
            new_retry_count = 1  # First retry
        else:
            new_retry_count = current_retry_count + 1

        # Check if we've exceeded the maximum retry limit first
        # This ensures terminal responses are returned even for retry requests
        # When retry_count > MAX, we've exceeded the limit and should stop
        # MAX_DANGEROUS_COMMAND_RETRIES=3 means we allow retry_count values 1, 2, 3
        limit_exceeded = new_retry_count > self._MAX_DANGEROUS_COMMAND_RETRIES

        # If limit exceeded, return terminal response (don't check _should_retry)
        if limit_exceeded:
            logger.warning(
                "Tool call retry limit exceeded for session %s: "
                "%d attempts blocked. Terminating with error.",
                session_id,
                new_retry_count,
            )
            terminal_response = self._create_terminal_response(
                retry_count=new_retry_count,
                session_id=session_id,
                is_streaming=True,
            )
            # Type narrowing: _create_terminal_response returns StreamingResponseEnvelope when is_streaming=True
            assert isinstance(terminal_response, StreamingResponseEnvelope)
            return terminal_response

        # Check if we should retry (handles edge cases like requests marked as retry but without retry_count)
        # Only check this after limit check, so we can return terminal responses when limit is exceeded
        if not self._should_retry(request, retry_state):
            return None

        # Guard against retry loops - check if new_retry_count would exceed the limit
        if new_retry_count > retry_state.max_retries:
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

        # Cancellation gate: ensure session is not cancelled before tool call retry
        session_key = resolve_session_key_from_request_context(context)
        if self._cancellation_coordinator is not None and session_key is not None:
            self._cancellation_coordinator.ensure_not_cancelled(session_key)

        # Execute retry request
        try:
            retry_response = await self._backend_processor.process_backend_request(
                request=retry_request, session_id=session_id, context=context
            )

            # Return raw backend response (no middleware processing)
            if isinstance(retry_response, StreamingResponseEnvelope):
                base_md = self._attach_retry_metadata(
                    metadata=retry_response.metadata or {},
                    retry_count=new_retry_count,
                    session_id=session_id,
                )

                async def _wrap_with_retry_metadata() -> (
                    AsyncIterator[ProcessedResponse]
                ):
                    if retry_response.content is None:
                        return
                    async for chunk in retry_response.content:
                        chunk_md = dict(getattr(chunk, "metadata", {}) or {})
                        for k, v in base_md.items():
                            chunk_md.setdefault(k, v)
                        yield ProcessedResponse(
                            content=getattr(chunk, "content", None),
                            metadata=chunk_md,
                            usage=getattr(chunk, "usage", None),
                        )

                return StreamingResponseEnvelope(
                    content=_wrap_with_retry_metadata(),
                    metadata=base_md,
                    headers=retry_response.headers,
                    status_code=retry_response.status_code,
                    media_type=retry_response.media_type,
                    cancel_callback=retry_response.cancel_callback,
                )
            # If non-streaming was returned for streaming request, wrap it
            if isinstance(retry_response, ResponseEnvelope):

                async def _wrap_stream() -> AsyncIterator[ProcessedResponse]:
                    yield ProcessedResponse(
                        content=retry_response.content,
                        metadata=retry_response.metadata or {},
                    )

                wrapped_md = self._attach_retry_metadata(
                    metadata=retry_response.metadata or {},
                    retry_count=new_retry_count,
                    session_id=session_id,
                )
                return StreamingResponseEnvelope(
                    content=_wrap_stream(), metadata=wrapped_md
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
