"""
Non-streaming response handler service.

This service processes non-streaming backend responses including:
- Response processor middleware invocation
- Empty-response retry with recovery prompt
- Structured output validation
- Metadata filtering and serialization
- Tool-call retry coordination

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 6.1, 7.1, 9.1, 9.2, 10.2
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic.types import JsonValue

from src.core.common.exceptions import BackendError
from src.core.common.session_key_resolver import (
    resolve_session_key_from_request_context,
)
from src.core.domain.backend_request_manager.context_models import (
    ResponseProcessingContext,
    ToolCallRetryState,
)
from src.core.domain.chat import CanonicalChatRequest, ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.backend_request_manager_components import (
    INonStreamingBackendResponseHandler,
    IStructuredOutputEnforcer,
    IToolCallRetryCoordinator,
)
from src.core.interfaces.response_processor_interface import (
    IResponseProcessor,
)
from src.core.interfaces.session_cancellation_coordinator_interface import (
    ISessionCancellationCoordinator,
)
from src.core.services.empty_response_middleware import EmptyResponseRetryError
from src.core.services.tool_call_retry_coordinator import ToolCallRetryCoordinator

logger = logging.getLogger(__name__)


def _filter_json_serializable_metadata(
    metadata: dict[str, Any],
) -> dict[str, JsonValue]:
    """Filter metadata to only include JSON-serializable values.

    Excludes non-serializable values like ChatRequest objects (original_request).

    Args:
        metadata: Source metadata dictionary

    Returns:
        Dictionary containing only JSON-serializable values
    """
    json_serializable_metadata: dict[str, JsonValue] = {}
    for key, value in metadata.items():
        # Skip non-JSON-serializable values like ChatRequest objects
        if key == "original_request":
            continue
        try:
            # Test if value is JSON-serializable
            json.dumps(value)
            # Type narrowing: value passed json.dumps check
            json_serializable_metadata[key] = value  # type: ignore[assignment]
        except (TypeError, ValueError):
            # Skip non-serializable values
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Skipping non-JSON-serializable metadata key: %s", key)
    return json_serializable_metadata


class BackendNonStreamingResponseHandler(INonStreamingBackendResponseHandler):
    """Handles non-streaming backend responses with processing and retry logic."""

    def __init__(
        self,
        response_processor: IResponseProcessor,
        structured_output_enforcer: IStructuredOutputEnforcer,
        tool_call_retry_coordinator: IToolCallRetryCoordinator,
        backend_processor: IBackendProcessor,
        app_state: IApplicationState,
        cancellation_coordinator: ISessionCancellationCoordinator | None = None,
    ) -> None:
        """Initialize the non-streaming response handler.

        Args:
            response_processor: Response processor for middleware pipeline
            structured_output_enforcer: Structured output validation enforcer
            tool_call_retry_coordinator: Tool-call retry coordinator
            backend_processor: Backend processor for retry requests
            app_state: Application state service
            cancellation_coordinator: Optional cancellation coordinator for gating retries
        """
        self._response_processor = response_processor
        self._structured_output_enforcer = structured_output_enforcer
        self._tool_call_retry_coordinator = tool_call_retry_coordinator
        self._backend_processor = backend_processor
        self._app_state = app_state
        self._cancellation_coordinator = cancellation_coordinator

    async def _create_retry_request(
        self, original_request: ChatRequest, recovery_prompt: str
    ) -> ChatRequest:
        """Create a retry request with the recovery prompt appended.

        Args:
            original_request: The original backend request
            recovery_prompt: Recovery prompt to append

        Returns:
            New request with recovery prompt appended
        """
        retry_messages = list(original_request.messages)
        recovery_message = ChatMessage(role="user", content=recovery_prompt)
        retry_messages.append(recovery_message)

        # Preserve tools and other fields while appending the recovery message
        return original_request.model_copy(update={"messages": retry_messages})

    async def handle(
        self,
        response: ResponseEnvelope,
        request: ChatRequest,
        context: RequestContext,
        processing_context: ResponseProcessingContext,
    ) -> ResponseEnvelope:
        """Return a processed non-streaming response envelope.

        Args:
            response: The backend response envelope
            request: The original backend request
            context: Request context
            processing_context: Typed processing context

        Returns:
            A processed response envelope with normalized content and metadata
        """
        try:
            # Enrich context with values from processing_context
            # Create a new RequestContext with backend and effective_model set
            original_request = (
                processing_context.original_request or context.original_request
            )
            # Set domain_request from original_request if it's a CanonicalChatRequest
            # and domain_request is not already set
            domain_request = context.domain_request
            if domain_request is None and isinstance(
                original_request, CanonicalChatRequest
            ):
                domain_request = original_request
            enriched_context = RequestContext(
                headers=context.headers,
                cookies=context.cookies,
                state=context.state,
                app_state=self._app_state,
                client_host=context.client_host,
                session_id=processing_context.session_id or context.session_id,
                request_id=context.request_id,
                agent=context.agent,
                original_request=original_request,
                processing_context=context.processing_context,
                domain_request=domain_request,
                raw_body=context.raw_body,
                backend=processing_context.backend_name,
                effective_model=processing_context.model_name,
                extensions=context.extensions,
                original_domain_request=context.original_domain_request,
            )

            # Process response through middleware pipeline
            # Pass enriched RequestContext - ResponseProcessor extracts needed values internally
            processed_response = await self._response_processor.process_response(
                response.content,
                processing_context.session_id,
                enriched_context,
            )

            # Handle empty-response retry
            # Note: EmptyResponseRetryError is raised by EmptyResponseFeature middleware
            # We catch it here and perform a single retry
            # BackendError is raised when max retries exceeded
        except EmptyResponseRetryError as e:
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Empty response detected for session %s, retrying with recovery prompt",
                    e.session_id,
                    exc_info=True,
                )

            # Cancellation gate: ensure session is not cancelled before empty response retry
            session_key = resolve_session_key_from_request_context(context)
            if self._cancellation_coordinator is not None and session_key is not None:
                self._cancellation_coordinator.ensure_not_cancelled(session_key)

            # Create retry request with recovery prompt
            retry_request = await self._create_retry_request(
                e.original_request, e.recovery_prompt
            )

            # Submit retry request to backend processor
            retry_response = await self._backend_processor.process_backend_request(
                request=retry_request,
                session_id=processing_context.session_id,
                context=context,
            )

            # Process retried response through handler again (recursive call)
            if isinstance(retry_response, ResponseEnvelope):
                return await self.handle(
                    response=retry_response,
                    request=retry_request,
                    context=context,
                    processing_context=processing_context,
                )
            else:
                # Streaming response from non-streaming request (shouldn't happen)
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Received streaming response for non-streaming request in session %s",
                        processing_context.session_id,
                        exc_info=True,
                    )
                # Convert to non-streaming by extracting first chunk

                # Type narrowing: retry_response must be StreamingResponseEnvelope here
                if retry_response.content is not None:
                    async for chunk in retry_response.content:
                        return ResponseEnvelope(
                            content=chunk.content,
                            metadata=chunk.metadata,
                            usage=chunk.usage,
                        )
                return response
        except BackendError as e:
            # BackendError raised when empty-response max retries exceeded
            # Re-raise to preserve error details and session_id
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Empty response retry limit exceeded for session %s: %s",
                    processing_context.session_id,
                    e.message,
                    exc_info=True,
                )
            raise

        # Apply structured output validation if schema is present
        # Check if validation already happened (via ResponseProcessor pipeline)
        # to prevent double-processing (design requirement: exactly-once validation)
        metadata = processed_response.metadata or {}
        if (
            processing_context.structured_output is not None
            and not metadata.get("structured_output_validated", False)
            and not metadata.get("schema_validation_attempted", False)
        ):
            try:
                processed_response = await self._structured_output_enforcer.enforce(
                    response=processed_response,
                    context=processing_context.structured_output,
                )
            except Exception as e:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        "Structured output validation failed for session %s: %s",
                        processing_context.session_id,
                        e,
                        exc_info=True,
                    )
                # Re-raise validation errors
                raise

        # Merge metadata from backend response to ensure transport flags are preserved
        # This is critical for flags like tool_call_swallowed that come from backend headers/metadata
        # Also preserve retry-related metadata from coordinator responses
        retry_metadata_keys = (
            "dangerous_command_retry_count",
            "tool_call_reactor_retry_count",
            "steering_retry_occurred",
            "tool_call_reactor_retry_failed",
        )
        if response.metadata:
            # ProcessedResponse.metadata is typed as dict[str, JsonValue] (non-optional)
            # so no None check needed
            for key, value in response.metadata.items():
                # Always preserve coordinator metadata (retry counts, steering flags)
                # This ensures retry metadata is preserved through recursive handler calls
                if key in retry_metadata_keys or key not in processed_response.metadata:
                    processed_response.metadata[key] = value

        # Detect swallowed tool calls and delegate to coordinator
        metadata = processed_response.metadata or {}
        if metadata.get("tool_call_swallowed") and not metadata.get(
            "tool_call_reactor_retry_failed"
        ):
            # Always delegate to coordinator when tool_call_swallowed is detected
            # The coordinator will check retry limits and return terminal response if exceeded
            # or None if retry is not allowed (already a retry request and limit not exceeded)
            extra_body = getattr(request, "extra_body", None) or {}
            # Build retry state from request metadata
            # Check both keys and use the higher value (for backward compatibility)
            retry_count = extra_body.get("_tool_call_reactor_retry_count", 0)
            legacy_count = extra_body.get("_dangerous_command_retry_count", 0)
            if isinstance(legacy_count, int) and legacy_count > retry_count:
                retry_count = legacy_count
            if not isinstance(retry_count, int):
                retry_count = 0
            # Use same max retries as ToolCallRetryCoordinator for consistency
            # Note: Using protected member for consistency with coordinator implementation
            # This should be refactored to use a public constant in the future
            max_retries = getattr(
                ToolCallRetryCoordinator, "_MAX_DANGEROUS_COMMAND_RETRIES", 3
            )

            retry_state = ToolCallRetryState(
                retry_count=retry_count,
                max_retries=max_retries,
                steering_message=None,
                is_streaming=False,
            )

            # Delegate to coordinator
            # Coordinator relies on ResponseEnvelope.metadata to detect swallowed tool calls.
            # The signal may originate from middleware processing, so forward the merged metadata.
            coordinator_response = ResponseEnvelope(
                content=response.content,
                metadata=metadata,
                headers=response.headers,
                status_code=response.status_code,
                media_type=response.media_type,
                usage=response.usage,
            )

            tool_call_retry_response = (
                await self._tool_call_retry_coordinator.handle_non_streaming(
                    request=request,
                    response=coordinator_response,
                    context=context,
                    retry_state=retry_state,
                )
            )

            if tool_call_retry_response is not None:
                # Coordinator returns ResponseEnvelope for non-streaming
                # Type narrowing: coordinator.handle_non_streaming returns ResponseEnvelope | None
                # tool_call_retry_response is guaranteed to be ResponseEnvelope here
                # Update request with retry count from response metadata before recursive processing
                retry_metadata = tool_call_retry_response.metadata or {}
                updated_extra_body = dict(getattr(request, "extra_body", None) or {})
                tool_call_retry_count_value = retry_metadata.get(
                    "tool_call_reactor_retry_count", retry_state.retry_count
                )
                updated_extra_body["_tool_call_reactor_retry_count"] = (
                    int(tool_call_retry_count_value)
                    if isinstance(tool_call_retry_count_value, int | float | str)
                    else retry_state.retry_count
                )
                dangerous_retry_count_value = retry_metadata.get(
                    "dangerous_command_retry_count", retry_state.retry_count
                )
                updated_extra_body["_dangerous_command_retry_count"] = (
                    int(dangerous_retry_count_value)
                    if isinstance(dangerous_retry_count_value, int | float | str)
                    else retry_state.retry_count
                )
                updated_extra_body["_tool_call_reactor_retry"] = True
                updated_request = request.model_copy(
                    update={"extra_body": updated_extra_body}
                )
                # Process the retry response through handler again (recursive call)
                return await self.handle(
                    response=tool_call_retry_response,
                    request=updated_request,
                    context=context,
                    processing_context=processing_context,
                )

                # Check if retry response is terminal to prevent infinite recursion
                retry_metadata = tool_call_retry_response.metadata or {}
                if retry_metadata.get(
                    "dangerous_command_limit_exceeded"
                ) or retry_metadata.get("session_terminated"):
                    # Terminal response - return as-is.
                    # Terminal envelopes are already user-facing and contain the required metadata.
                    return tool_call_retry_response

                # Process retried response through full pipeline again
                # Note: The coordinator should have marked the retry request with _tool_call_reactor_retry
                # to prevent infinite recursion, but we check here as well for safety
                # Continue recursion with an updated request that carries the incremented retry counters.
                # This preserves monotonic retry counts across multiple swallowed responses.
                updated_extra_body = dict(getattr(request, "extra_body", None) or {})
                tool_call_retry_count_value = retry_metadata.get(
                    "tool_call_reactor_retry_count", retry_state.retry_count
                )
                updated_extra_body["_tool_call_reactor_retry_count"] = (
                    int(tool_call_retry_count_value)
                    if isinstance(tool_call_retry_count_value, int | float | str)
                    else retry_state.retry_count
                )
                dangerous_retry_count_value = retry_metadata.get(
                    "dangerous_command_retry_count", retry_state.retry_count
                )
                updated_extra_body["_dangerous_command_retry_count"] = (
                    int(dangerous_retry_count_value)
                    if isinstance(dangerous_retry_count_value, int | float | str)
                    else retry_state.retry_count
                )
                updated_extra_body["_tool_call_reactor_retry"] = True
                next_request = request.model_copy(
                    update={"extra_body": updated_extra_body}
                )

                return await self.handle(
                    response=tool_call_retry_response,
                    request=next_request,
                    context=context,
                    processing_context=processing_context,
                )

        # Preserve retry-related metadata from coordinator responses BEFORE filtering
        # This ensures retry counts and steering flags are preserved through the pipeline
        retry_metadata_keys = (
            "dangerous_command_retry_count",
            "tool_call_reactor_retry_count",
            "steering_retry_occurred",
            "tool_call_reactor_retry_failed",
        )
        preserved_retry_metadata = {}
        # Get retry metadata from response envelope (coordinator attaches it here)
        if response.metadata:
            for key in retry_metadata_keys:
                if key in response.metadata:
                    preserved_retry_metadata[key] = response.metadata[key]
        # Also check processed_response metadata (in case it was already merged)
        if processed_response.metadata:
            for key in retry_metadata_keys:
                if (
                    key in processed_response.metadata
                    and key not in preserved_retry_metadata
                ):
                    preserved_retry_metadata[key] = processed_response.metadata[key]

        # Filter metadata to JSON-serializable values and remove original_request
        filtered_metadata = _filter_json_serializable_metadata(
            processed_response.metadata or {}
        )

        # Restore preserved retry metadata (overwrites any filtered values)
        filtered_metadata.update(preserved_retry_metadata)

        # Ensure session_id is included in response metadata (requirement 9.2)
        if "session_id" not in filtered_metadata:
            filtered_metadata["session_id"] = processing_context.session_id

        # Build final response envelope
        result = ResponseEnvelope(
            content=processed_response.content,
            metadata=filtered_metadata,
            usage=processed_response.usage,
            headers=response.headers,
            status_code=response.status_code,
            media_type=response.media_type,
        )

        return result
