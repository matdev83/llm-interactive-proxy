"""Tool-call reactor orchestrator.

This module implements the orchestrator that coordinates tool-call processing
across extraction, normalization, deduplication, parsing, fixups, reactor invocation,
and replacement creation.
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast

from pydantic.types import JsonValue

from src.core.common.logging_utils import get_logger
from src.core.domain.chat import ToolCall
from src.core.interfaces.end_of_session_service_interface import (
    IEndOfSessionService,
)
from src.core.interfaces.replacement_response_factory_interface import (
    IReplacementResponseFactory,
    ToolCallReactionMetadata,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.tool_arguments_fixup_pipeline_interface import (
    FixupContext,
    IToolArgumentsFixupPipeline,
)
from src.core.interfaces.tool_arguments_parser_interface import IToolArgumentsParser
from src.core.interfaces.tool_call_deduplicator_interface import IToolCallDeduplicator
from src.core.interfaces.tool_call_extractor_interface import IToolCallExtractor
from src.core.interfaces.tool_call_normalizer_interface import IToolCallNormalizer
from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallReactor,
    ToolCallContext,
)
from src.core.interfaces.tool_call_reactor_orchestrator_interface import (
    IToolCallReactorOrchestrator,
    ToolCallReactorContext,
)
from src.core.interfaces.tool_call_stream_context_resolver_interface import (
    IToolCallStreamContextResolver,
)
from src.tool_call_loop.lifecycle_registry import (
    ToolCallLifecycleRegistry,
    build_tool_call_signature,
)

logger = get_logger(__name__)

# Fallback steering used when a handler swallows a tool call but does not provide
# explicit steering text. This message is intended for the REMOTE LLM backend and
# must never be shown directly to the client.
_DEFAULT_BACKEND_STEERING_MESSAGE = (
    "A tool call was blocked by proxy policy. Do not repeat the blocked tool call. "
    "Respond to the user with a compliant approach that does not require tools."
)


class ToolCallReactorOrchestrator(IToolCallReactorOrchestrator):
    """Orchestrator for tool-call processing.

    This orchestrator coordinates the end-to-end flow of tool-call processing:
    - Bypass checks (bypass flag, VTC marker, no tool calls)
    - Extraction and normalization of tool calls
    - Deduplication and lifecycle tracking
    - Argument parsing and fixups
    - Reactor invocation
    - Replacement response creation for swallowed calls

    The orchestrator preserves fail-open behavior: exceptions during processing
    do not crash the request.
    """

    def __init__(
        self,
        extractor: IToolCallExtractor,
        normalizer: IToolCallNormalizer,
        stream_context_resolver: IToolCallStreamContextResolver,
        deduplicator: IToolCallDeduplicator,
        arguments_parser: IToolArgumentsParser,
        arguments_fixup_pipeline: IToolArgumentsFixupPipeline,
        reactor: IToolCallReactor,
        replacement_factory: IReplacementResponseFactory,
        lifecycle_registry: ToolCallLifecycleRegistry,
        end_of_session_service: IEndOfSessionService | None = None,
    ) -> None:
        """Initialize the orchestrator with injected dependencies.

        Args:
            extractor: Extractor for tool calls from response objects.
            normalizer: Normalizer for tool-call objects to dictionaries.
            stream_context_resolver: Resolver for stream context and buffer state.
            deduplicator: Deduplicator for filtering new tool calls.
            arguments_parser: Parser for tool arguments with repair.
            arguments_fixup_pipeline: Pipeline for applying argument fixups.
            reactor: Reactor service for handler invocation.
            replacement_factory: Factory for building replacement responses.
            lifecycle_registry: Registry for lifecycle tracking and stream state clearing.
            end_of_session_service: Optional service for checking if session has ended.
        """
        self._extractor = extractor
        self._normalizer = normalizer
        self._stream_context_resolver = stream_context_resolver
        self._deduplicator = deduplicator
        self._arguments_parser = arguments_parser
        self._arguments_fixup_pipeline = arguments_fixup_pipeline
        self._reactor = reactor
        self._replacement_factory = replacement_factory
        self._lifecycle_registry = lifecycle_registry
        self._end_of_session_service = end_of_session_service

    async def handle(
        self,
        response: ProcessedResponse,
        session_id: str,
        context: ToolCallReactorContext,
        is_streaming: bool,
    ) -> ProcessedResponse:
        """Process a response for tool calls and return either original or replacement.

        This method orchestrates the complete tool-call processing flow.
        """
        # Bypass check: VTC tool calls
        metadata = getattr(response, "metadata", None)
        if isinstance(metadata, dict) and metadata.get("vtc_tool_calls"):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Skipping reactor processing for VTC tool calls "
                    "(already processed by VTCResponseStreamWrapper) in session %s",
                    session_id,
                )
            # Use stream key from context for state reset
            stream_key = context.stream_key
            if not stream_key:
                stream_key = self._stream_context_resolver.resolve_stream_key(
                    session_id, None, response
                )
            await self._reset_stream_state_if_needed(stream_key, response, is_streaming)
            return response

        # Use stream key from context (already resolved by feature/middleware)
        # Fall back to resolver if not set (shouldn't happen in normal flow)
        stream_key = context.stream_key
        if not stream_key:
            stream_key = self._stream_context_resolver.resolve_stream_key(
                session_id, None, response
            )
        buffer_state = context.buffer_state

        # Extract tool calls from response (fail-open per requirement 6.2)
        try:
            raw_tool_calls = self._extractor.extract(response)
        except Exception as e:
            logger.error(
                "Error extracting tool calls from response in session %s: %s",
                session_id,
                e,
                exc_info=True,
            )
            await self._reset_stream_state_if_needed(stream_key, response, is_streaming)
            return response

        if not raw_tool_calls:
            await self._reset_stream_state_if_needed(stream_key, response, is_streaming)
            return response

        # Normalize tool calls to dictionaries (fail-open per requirement 6.2)
        normalized_tool_calls: list[dict[str, Any]] = []
        try:
            for raw_call in raw_tool_calls:
                normalized = self._normalizer.normalize(raw_call)
                if normalized:
                    normalized_tool_calls.append(normalized)
        except Exception as e:
            logger.error(
                "Error normalizing tool calls in session %s: %s",
                session_id,
                e,
                exc_info=True,
            )
            await self._reset_stream_state_if_needed(stream_key, response, is_streaming)
            return response

        if not normalized_tool_calls:
            await self._reset_stream_state_if_needed(stream_key, response, is_streaming)
            return response

        # Convert normalized dicts to ToolCall domain models
        tool_calls: list[ToolCall] = []
        for normalized_dict in normalized_tool_calls:
            try:
                tool_call = ToolCall(**normalized_dict)
                tool_calls.append(tool_call)
            except Exception as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to convert normalized tool call to ToolCall: %s",
                        e,
                        exc_info=True,
                    )
                continue

        if not tool_calls:
            await self._reset_stream_state_if_needed(stream_key, response, is_streaming)
            return response

        # Early exit if session has already ended (performance optimization)
        if self._end_of_session_service:
            try:
                if await self._end_of_session_service.has_ended(session_id):
                    await self._reset_stream_state_if_needed(
                        stream_key, response, is_streaming
                    )
                    return response
            except Exception as e:
                # Fail-open: if EoS check fails, continue processing
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Error checking session end status for %s: %s",
                        session_id,
                        e,
                        exc_info=True,
                    )

        # Filter to new tool calls via deduplicator
        # Note: deduplicator handles buffered calls internally
        new_tool_calls = await self._deduplicator.filter_new_calls(
            tool_calls=tool_calls,
            stream_key=stream_key,
            buffer_state=buffer_state,
            is_streaming=is_streaming,
        )

        if not new_tool_calls:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "All %d tool call(s) already processed in session %s, "
                    "skipping reactor execution",
                    len(tool_calls),
                    session_id,
                )
            await self._reset_stream_state_if_needed(stream_key, response, is_streaming)
            return response

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Detected %d new tool call(s) in session %s (stream=%s, total=%d)",
                len(new_tool_calls),
                session_id,
                stream_key,
                len(tool_calls),
            )

        # Expose tool calls in metadata (for backward compatibility)
        try:
            if hasattr(response, "metadata"):
                response.metadata.setdefault("tool_calls", [])
                existing_calls = response.metadata.get("tool_calls")

                replace_metadata_calls = False
                if (
                    not isinstance(existing_calls, list)
                    or not existing_calls
                    or not all(isinstance(item, dict) for item in existing_calls)
                ):
                    replace_metadata_calls = True

                if replace_metadata_calls:
                    clean_tool_calls: list[JsonValue] = []
                    for tc_dict in normalized_tool_calls:
                        clean_tc: dict[str, JsonValue] = {
                            k: cast(JsonValue, v)
                            for k, v in tc_dict.items()
                            if k != "_already_processed"
                        }
                        clean_tool_calls.append(clean_tc)
                    response.metadata["tool_calls"] = clean_tool_calls
        except (TypeError, ValueError, KeyError, AttributeError):
            # Log unexpected errors during metadata annotation at WARNING level
            # to ensure visibility even when DEBUG logging is disabled
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to annotate tool calls in metadata",
                    exc_info=True,
                )

        # Process each new tool call through the reactor
        for tool_call in new_tool_calls:
            # Cache model_dump() to avoid repeated calls per tool call (used for signature + write-back)
            tool_call_dict = tool_call.model_dump()
            signature = build_tool_call_signature(tool_call_dict)

            # Double-check if already processed (defensive)
            if await self._deduplicator.is_processed(stream_key, signature):
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Skipping already-processed tool call (signature=%s) "
                        "for stream %s",
                        signature,
                        stream_key,
                    )
                continue

            # Get session context from response metadata
            backend_name = None
            model_name = None
            calling_agent = None
            if isinstance(metadata, dict):
                backend_name = metadata.get("backend_name", "unknown")
                model_name = metadata.get("model_name", "unknown")
                calling_agent = metadata.get("calling_agent")

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Processing tool call signature=%s session=%s stream=%s backend=%s model=%s",
                    signature,
                    session_id,
                    stream_key,
                    backend_name,
                    model_name,
                )

            # Extract function payload
            function_payload = tool_call.function
            tool_name = function_payload.name
            if not tool_name:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Skipping tool call with missing name in session %s",
                        session_id,
                    )
                continue

            raw_arguments = function_payload.arguments

            # Parse arguments
            envelope = self._arguments_parser.parse(raw_arguments)

            # Apply fixups
            fixup_context = FixupContext(
                tool_name=tool_name,
                backend_name=backend_name,
                calling_agent=calling_agent,
                client_os=context.client_os,
            )
            envelope = self._arguments_fixup_pipeline.apply_fixups(
                envelope, fixup_context
            )

            # Write back modified arguments if fixups were applied
            if envelope.was_modified_by_fixups:
                self._write_back_modified_arguments(
                    tool_call_dict, envelope.normalized_arguments.root
                )

            # Build ToolCallContext (convert normalized args to dict at boundary)
            full_response = getattr(response, "content", None)
            tool_context = ToolCallContext(
                session_id=session_id,
                backend_name=backend_name or "unknown",
                model_name=model_name or "unknown",
                full_response=full_response,
                tool_name=tool_name or "unknown",
                tool_arguments=envelope.normalized_arguments.root,
                calling_agent=calling_agent,
            )

            # Invoke reactor (fail-open)
            try:
                result = await self._reactor.process_tool_call(tool_context)

                # Mark as processed
                await self._deduplicator.mark_processed(
                    stream_key, signature, buffer_state
                )

                # If swallowed, build replacement and return
                if result and result.should_swallow:
                    logger.info(
                        "Tool call '%s' was swallowed by reactor in session %s",
                        tool_context.tool_name,
                        session_id,
                    )

                    steering_message = result.replacement_response
                    if (
                        not isinstance(steering_message, str)
                        or not steering_message.strip()
                    ):
                        steering_message = _DEFAULT_BACKEND_STEERING_MESSAGE

                    # Build reaction metadata
                    reaction_metadata = None
                    if result.metadata:
                        reaction_metadata = ToolCallReactionMetadata(
                            reaction_type="swallowed",
                            reactor_name=result.metadata.get("reactor_name"),
                        )

                    replacement_response = self._replacement_factory.build_replacement(
                        original_response=response,
                        replacement_content=steering_message,
                        original_tool_call=tool_call,
                        reaction_metadata=reaction_metadata,
                    )
                    # Reset stream state before returning replacement response
                    await self._reset_stream_state_if_needed(
                        stream_key, response, is_streaming
                    )
                    return replacement_response

            except Exception as e:
                logger.error(
                    "Error processing tool call through reactor in session %s: %s",
                    session_id,
                    e,
                    exc_info=True,
                )
                # Mark as processed even on error to prevent retry loops
                await self._deduplicator.mark_processed(
                    stream_key, signature, buffer_state
                )

        # No swallows occurred, return original response
        await self._reset_stream_state_if_needed(stream_key, response, is_streaming)
        return response

    def _should_reset_stream_state(
        self, response: ProcessedResponse, is_streaming: bool
    ) -> bool:
        """Determine if stream state should be reset."""
        metadata = getattr(response, "metadata", None)
        if isinstance(metadata, dict):
            if metadata.get("is_done"):
                return True
            if not is_streaming:
                finish_reason = metadata.get("finish_reason")
                if finish_reason in {"stop", "length", "tool_calls"}:
                    return True
        # Don't clear lifecycle registry for non-streaming responses without finish_reason
        # to allow deduplication across multiple process() calls
        return False

    async def _reset_stream_state_if_needed(
        self,
        stream_key: str,
        response: ProcessedResponse,
        is_streaming: bool,
    ) -> None:
        """Reset stream state if needed."""
        if self._should_reset_stream_state(response, is_streaming):
            await self._lifecycle_registry.clear_stream(stream_key)

    @staticmethod
    def _write_back_modified_arguments(
        tool_call: dict[str, Any],
        new_arguments: Any,
    ) -> None:
        """Write modified arguments back to the tool call dict.

        Args:
            tool_call: The tool call dict to modify
            new_arguments: The new arguments to write back
        """
        function_payload = tool_call.get("function")
        if not isinstance(function_payload, dict):
            return

        original_args = function_payload.get("arguments")
        if isinstance(original_args, str):
            if isinstance(new_arguments, dict):
                function_payload["arguments"] = json.dumps(new_arguments)
            else:
                function_payload["arguments"] = str(new_arguments)
        else:
            function_payload["arguments"] = new_arguments
