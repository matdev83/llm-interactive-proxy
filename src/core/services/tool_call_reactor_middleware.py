"""
Tool Call Reactor Middleware.

This middleware integrates the tool call reactor system into the response processing pipeline.
It detects tool calls in LLM responses and passes them through registered handlers.
"""

from __future__ import annotations

import contextlib
import json
import logging
from dataclasses import asdict, is_dataclass
from typing import Any

from json_repair import repair_json

from src.core.common.logging_utils import get_logger
from src.core.domain.responses import ProcessedResponse
from src.core.interfaces.response_processor_interface import IResponseMiddleware
from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallReactor,
    ToolCallContext,
)
from src.core.services.streaming.stream_context_registry import (
    ToolCallBufferState,
    get_global_streaming_context_registry,
)
from src.tool_call_loop.lifecycle_registry import (
    ToolCallLifecycleRegistry,
    build_tool_call_signature,
)

logger = get_logger(__name__)

# Marker key used to track if a tool call has been processed
_TOOL_CALL_PROCESSING_MARKER = "_already_processed"


class ToolCallReactorMiddleware(IResponseMiddleware):
    """Middleware that integrates tool call reactor into the response pipeline.

    This middleware detects tool calls in LLM responses and passes them through
    the tool call reactor system, allowing handlers to react to tool calls and
    potentially modify the response.
    """

    def __init__(
        self,
        tool_call_reactor: IToolCallReactor,
        enabled: bool = True,
        priority: int = -10,
        lifecycle_registry: ToolCallLifecycleRegistry | None = None,
    ):
        """Initialize the tool call reactor middleware.

        Args:
            tool_call_reactor: The tool call reactor service
            enabled: Whether middleware is enabled
            priority: Priority of this middleware (lower numbers run later)
        """
        self._tool_call_reactor = tool_call_reactor
        self._enabled = enabled
        self._priority = priority
        self._lifecycle = lifecycle_registry or ToolCallLifecycleRegistry(
            max_streams=1024
        )

    @property
    def priority(self) -> int:
        """Get the middleware priority."""
        return self._priority

    async def process(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool = False,
        stop_event: Any = None,
    ) -> Any:
        """Process a response and check for tool calls.

        Args:
            response: The response to process
            session_id: The session ID
            context: Additional context
            is_streaming: Whether this is a streaming response
            stop_event: Optional stop event for streaming

        Returns:
            The processed response (potentially modified by handlers)
        """
        if not self._enabled or context.get("bypass_tool_call_reactor"):
            return response

        stream_key = self._resolve_stream_key(session_id, context, response)
        buffer_state = self._resolve_buffer_state(context, stream_key)

        # Non-streaming responses should not retain lifecycle state between calls
        if not is_streaming:
            self._clear_stream_state(stream_key)

        # Extract tool calls from various possible locations
        tool_calls: list[dict[str, Any]] = []
        raw_tool_calls: list[Any] = []  # Keep track of original objects
        buffered_call_count = 0  # Track how many calls came from the buffer

        # For streaming responses with shared buffer state, consume buffered calls first
        if buffer_state is not None and is_streaming:
            buffered_calls = self._consume_buffered_calls(buffer_state)
            if buffered_calls:
                tool_calls.extend(buffered_calls)
                raw_tool_calls.extend(buffered_calls)
                buffered_call_count = len(buffered_calls)

        # Priority 1: Direct 'tool_calls' attribute (e.g., on ChatMessage)
        if (
            hasattr(response, "tool_calls")
            and response.tool_calls
            and isinstance(response.tool_calls, list)
        ) and not tool_calls:
            for raw_call in response.tool_calls:
                normalized = self._normalize_tool_call(raw_call)
                if normalized:
                    tool_calls.append(normalized)
                    raw_tool_calls.append(raw_call)

        # Priority 2: 'tool_calls' within a 'metadata' attribute
        if not tool_calls:
            try:
                meta_calls = getattr(response, "metadata", {}).get("tool_calls")
                if isinstance(meta_calls, list):
                    for raw_call in meta_calls:
                        normalized = self._normalize_tool_call(raw_call)
                        if normalized:
                            tool_calls.append(normalized)
                            raw_tool_calls.append(raw_call)
            except Exception as e:
                if logger.is_enabled_for(logging.DEBUG):
                    logger.debug(
                        "Error extracting tool calls from metadata: %s",
                        e,
                        exc_info=True,
                    )

        # Priority 3: Extract from 'content' attribute as a fallback
        if not tool_calls:
            content = getattr(response, "content", None)
            if content:
                tool_calls = self._extract_tool_calls(content)
                # For content-extracted tool calls, they are already dicts
                raw_tool_calls = tool_calls
        if not tool_calls:
            self._reset_stream_state_if_needed(stream_key, response, is_streaming)
            return response

        # For proper handling of session state changes between requests, process all tool calls
        # without cross-request persistence of processed state
        new_tool_calls_with_raw: list[tuple[dict[str, Any], Any]] = []

        for i, tc in enumerate(tool_calls):
            raw_tc = raw_tool_calls[i] if i < len(raw_tool_calls) else tc

            already_processed = tc.get(_TOOL_CALL_PROCESSING_MARKER, False)
            if not already_processed and raw_tc is not tc:
                already_processed = bool(
                    getattr(raw_tc, _TOOL_CALL_PROCESSING_MARKER, False)
                )

            if already_processed:
                continue

            # For buffered calls (those that came from ToolCallRepairProcessor via buffer_state),
            # skip lifecycle dedup check since ToolCallRepairProcessor already deduplicates
            # at buffer level using detected_signatures. Non-buffered calls (extracted from
            # response attributes) still need lifecycle dedup check.
            is_from_buffer = i < buffered_call_count

            if not is_from_buffer and is_streaming:
                # In streaming mode, only process non-buffered tool calls when the response
                # is complete. This prevents processing partial tool calls (e.g., during
                # argument generation) which would burn the lifecycle signature and cause
                # the complete tool call to be skipped later.
                if not self._is_response_complete(response):
                    continue

            if not is_from_buffer:
                # Check lifecycle registry for non-buffered calls
                signature = build_tool_call_signature(tc)
                is_new = self._lifecycle.register_detection(stream_key, signature)
                if not is_new:
                    continue

            new_tool_calls_with_raw.append((tc, raw_tc))

        # Log skipped tool calls
        skipped_count = len(tool_calls) - len(new_tool_calls_with_raw)
        if skipped_count > 0 and logger.is_enabled_for(logging.DEBUG):
            logger.debug(
                f"Skipped {skipped_count} already-processed tool call(s) in session {session_id}"
            )

        if not new_tool_calls_with_raw:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"All {len(tool_calls)} tool call(s) already processed in session {session_id}, skipping reactor execution"
                )
            self._reset_stream_state_if_needed(stream_key, response, is_streaming)
            return response

        if logger.is_enabled_for(logging.DEBUG):
            logger.debug(
                f"Detected {len(new_tool_calls_with_raw)} new tool call(s) in session {session_id}"
            )

        # Get session context information
        backend_name = context.get("backend_name", "unknown")
        model_name = context.get("model_name", "unknown")
        calling_agent = context.get("calling_agent")

        # Expose detected tool calls in response metadata for downstream consumers
        try:
            if hasattr(response, "metadata") and isinstance(response.metadata, dict):
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
                    # Store clean copies without the processing marker to avoid cross-session contamination
                    clean_tool_calls = []
                    for tc in tool_calls:
                        clean_tc = {
                            k: v
                            for k, v in tc.items()
                            if k != _TOOL_CALL_PROCESSING_MARKER
                        }
                        clean_tool_calls.append(clean_tc)
                    response.metadata["tool_calls"] = clean_tool_calls
            # Also pass via context so processors can use them even if metadata is overwritten later
            if isinstance(context, dict):
                context["detected_tool_calls"] = list(tool_calls)
        except Exception:
            if logger.is_enabled_for(logging.DEBUG):
                logger.debug(
                    "Failed to annotate tool calls in metadata/context", exc_info=True
                )

        # Process each new tool call through the reactor
        for tool_call, raw_tool_call in new_tool_calls_with_raw:
            signature = build_tool_call_signature(tool_call)
            if self._lifecycle.is_processed(stream_key, signature):
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Skipping already-processed tool call (signature=%s) for stream %s",
                        signature,
                        stream_key,
                    )
                continue
            function_payload = tool_call.get("function")

            if not isinstance(function_payload, dict):
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Skipping non-function tool call type: %s",
                        type(function_payload).__name__,
                    )
                continue

            # Parse tool arguments if they are a JSON string
            tool_arguments_raw = function_payload.get("arguments", {})
            tool_arguments: Any = {}
            if isinstance(tool_arguments_raw, str):
                parsed_args, repair_outcome = self._attempt_parse_tool_arguments(
                    tool_arguments_raw
                )
                self._record_argument_repair_outcome(repair_outcome)

                if parsed_args is None:
                    # Preserve the original value so downstream handlers still
                    # receive the raw arguments string.
                    tool_arguments = tool_arguments_raw
                elif isinstance(parsed_args, dict | list):
                    tool_arguments = parsed_args
                else:
                    tool_arguments = parsed_args
            elif isinstance(tool_arguments_raw, dict | list):
                tool_arguments = tool_arguments_raw
            else:
                tool_arguments = tool_arguments_raw

            full_response = getattr(response, "content", None)

            tool_context = ToolCallContext(
                session_id=session_id,
                backend_name=backend_name,
                model_name=model_name,
                full_response=full_response,
                tool_name=function_payload.get("name", "unknown"),
                tool_arguments=tool_arguments,
                calling_agent=calling_agent,
            )

            try:
                result = await self._tool_call_reactor.process_tool_call(tool_context)

                # Mark tool call as processed after reactor execution
                # Mark both the normalized dict and the raw object
                self._mark_tool_call_processed(
                    tool_call, raw_tool_call, stream_key, signature, buffer_state
                )

                if result and result.should_swallow:
                    logger.info(
                        f"Tool call '{tool_context.tool_name}' was swallowed by reactor "
                        f"in session {session_id}"
                    )

                    # Create a new response with the replacement content
                    if result.replacement_response is not None:
                        replacement_response = self._create_replacement_response(
                            response,
                            result.replacement_response,
                            tool_call,
                            result.metadata,
                        )
                        return replacement_response
                    else:
                        logger.warning(
                            f"Handler swallowed tool call '{tool_context.tool_name}' "
                            f"but provided no replacement response"
                        )

            except Exception as e:
                logger.error(
                    f"Error processing tool call through reactor: {e}",
                    exc_info=True,
                )
                # Mark as processed even on error to avoid retry loops
                self._mark_tool_call_processed(
                    tool_call, raw_tool_call, stream_key, signature, buffer_state
                )

        self._reset_stream_state_if_needed(stream_key, response, is_streaming)

        return response

    def get_registered_handlers(self) -> list[str]:
        """Get the names of all registered handlers in the underlying reactor.

        Returns:
            List of handler names.
        """
        return self._tool_call_reactor.get_registered_handlers()

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the middleware.

        Args:
            enabled: Whether the middleware should be enabled.
        """
        self._enabled = enabled

    def _attempt_parse_tool_arguments(
        self, raw_arguments: str
    ) -> tuple[Any | None, str]:
        """Attempt to parse tool arguments string with repair and relaxed fallback."""
        repair_outcome = "failed"
        candidates: list[str] = []
        last_error: Exception | None = None

        try:
            repaired = repair_json(raw_arguments)
            if isinstance(repaired, str):
                candidates.append(repaired)
        except Exception:
            # Best-effort repair; fall back to original string
            pass

        if raw_arguments not in candidates:
            candidates.append(raw_arguments)

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
                repair_outcome = "success"
                return parsed, repair_outcome
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                last_error = exc
                try:
                    parsed_relaxed = json.loads(candidate, strict=False)
                    repair_outcome = "recovered"
                    return parsed_relaxed, repair_outcome
                except (json.JSONDecodeError, TypeError, ValueError) as relaxed_exc:
                    last_error = relaxed_exc
                    continue

        if last_error is not None:
            logger.warning(
                "Could not parse tool arguments after repair attempts: %s",
                last_error,
                exc_info=True,
            )
        else:
            logger.warning("Could not parse tool arguments after repair attempts")
        return None, repair_outcome

    def _record_argument_repair_outcome(self, outcome: str) -> None:
        """Forward argument repair telemetry to the underlying reactor if supported."""
        recorder = getattr(
            self._tool_call_reactor, "record_tool_argument_repair_outcome", None
        )
        if callable(recorder):
            recorder(outcome)

    def _resolve_buffer_state(
        self, context: dict[str, Any] | None, stream_key: str
    ) -> ToolCallBufferState | None:
        if not context:
            return None
        candidate = context.get("tool_call_buffer_state")
        if isinstance(candidate, ToolCallBufferState):
            return candidate

        stream_identifier = (
            context.get("stream_id") or context.get("response_stream_id") or stream_key
        )
        if not stream_identifier or stream_identifier == "anonymous-stream":
            return None

        try:
            registry = get_global_streaming_context_registry()
            return registry.get_tool_call_buffer(str(stream_identifier))
        except Exception:
            return None

    @staticmethod
    def _consume_buffered_calls(
        buffer_state: ToolCallBufferState,
    ) -> list[dict[str, Any]]:
        if not buffer_state.detected_calls:
            return []
        if buffer_state.reactor_cursor >= len(buffer_state.detected_calls):
            return []
        calls = buffer_state.detected_calls[buffer_state.reactor_cursor :]
        buffer_state.reactor_cursor = len(buffer_state.detected_calls)
        return calls

    def _extract_tool_calls(self, content: Any) -> list[dict[str, Any]]:
        """Extract tool calls from response content.

        Args:
            content: The response content to extract tool calls from

        Returns:
            List of tool call dictionaries
        """
        # Normalize the content into a Python structure that can be inspected
        if isinstance(content, dict | list):
            data = content
        elif isinstance(content, str):
            try:
                data = json.loads(content)
            except (json.JSONDecodeError, TypeError, ValueError):
                return []
        else:
            return []

        tool_calls = []

        # Check for OpenAI format
        if isinstance(data, dict):
            choices = data.get("choices", [])
            for choice in choices:
                message = choice.get("message", {})
                message_tool_calls = message.get("tool_calls", [])
                if (
                    message_tool_calls
                    and isinstance(message_tool_calls, list)
                    and all(isinstance(item, dict) for item in message_tool_calls)
                ):
                    tool_calls.extend(message_tool_calls)

        # Check for direct tool calls array
        if (
            isinstance(data, list)
            and data
            and all(isinstance(item, dict) and "function" in item for item in data)
        ):
            tool_calls.extend(data)

        return tool_calls

    def _normalize_tool_call(self, tool_call: Any) -> dict[str, Any] | None:
        """Normalize a tool call entry from metadata into a dictionary.

        Args:
            tool_call: The tool call object to normalize

        Returns:
            The normalized tool call as a dictionary, or None if it cannot be normalized
        """
        # If already a dict, return as-is
        if isinstance(tool_call, dict):
            return tool_call

        # If it's a Pydantic model, use model_dump
        if hasattr(tool_call, "model_dump"):
            try:
                result = tool_call.model_dump()
                # Ensure the result is a dict
                if isinstance(result, dict):
                    return result
                return None
            except (TypeError, ValueError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"Failed to convert Pydantic model to dict: {e}")
                return None

        # If it's a dataclass, convert to dict
        if is_dataclass(tool_call) and not isinstance(tool_call, type):
            try:
                return asdict(tool_call)
            except (TypeError, ValueError) as e:
                if logger.is_enabled_for(logging.DEBUG):
                    logger.debug(f"Failed to convert dataclass to dict: {e}")
                return None

        # Otherwise, we can't normalize it
        if logger.is_enabled_for(logging.DEBUG):
            logger.debug(
                "Cannot normalize tool call object: %s", tool_call, exc_info=True
            )
        return None

    def _create_replacement_response(
        self,
        original_response: Any,
        replacement_content: str,
        original_tool_call: dict[str, Any],
        reaction_metadata: dict[str, Any] | None = None,
    ) -> Any:
        """Create a replacement response with steering content.

        Args:
            original_response: The original response object
            replacement_content: The replacement content from the handler
            original_tool_call: The original tool call that was swallowed
            reaction_metadata: Additional metadata from the handler reaction

        Returns:
            A new response object with the replacement content
        """
        # If the original response has a content attribute, create a new ProcessedResponse
        if hasattr(original_response, "content"):
            original_content = getattr(original_response, "content", None)

            # Create a new ProcessedResponse with the replacement content
            original_metadata = getattr(original_response, "metadata", {}) or {}
            # Handle case where metadata might be a mock or non-dict
            merged_metadata: dict[str, Any] = (
                dict(original_metadata) if isinstance(original_metadata, dict) else {}
            )

            if reaction_metadata:
                existing_reactor_metadata = {}
                if isinstance(merged_metadata.get("tool_call_reactor"), dict):
                    existing_reactor_metadata = {
                        **merged_metadata["tool_call_reactor"],
                    }
                merged_metadata["tool_call_reactor"] = {
                    **existing_reactor_metadata,
                    **reaction_metadata,
                }

            swallowed_tool_calls: list[dict[str, Any]] = []
            existing_tool_calls = merged_metadata.get("tool_calls")
            if isinstance(existing_tool_calls, list):
                for tc in existing_tool_calls:
                    if isinstance(tc, dict):
                        swallowed_tool_calls.append(dict(tc))
            if "tool_calls" in merged_metadata:
                merged_metadata.pop("tool_calls", None)

            tool_call_id = None
            tool_name = None
            if isinstance(original_tool_call, dict):
                tool_call_id = original_tool_call.get("id")
                function_payload = original_tool_call.get("function")
                if isinstance(function_payload, dict):
                    tool_name = function_payload.get("name")

            merged_metadata.update(
                {
                    "tool_call_swallowed": True,
                    "original_tool_call": original_tool_call,
                    "replacement_provided": True,
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "finish_reason": "stop",
                    "tool_name": tool_name,
                    "steering_message": replacement_content,
                    "swallowed_tool_calls": swallowed_tool_calls,
                    "swallowed_original_content": (
                        original_content if isinstance(original_content, str) else None
                    ),
                }
            )

            # Construct OpenAI-compatible response structure
            import time

            # Try to preserve model name from metadata or context
            model_name = merged_metadata.get("model", "steering-agent")

            replacement_struct = {
                "id": f"chatcmpl-steering-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model_name,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": replacement_content,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": getattr(original_response, "usage", None),
            }

            # Ensure content type consistency with original response
            content: str | dict[str, Any] = replacement_struct
            if isinstance(original_content, str):
                with contextlib.suppress(Exception):
                    content = json.dumps(replacement_struct)

            new_response = ProcessedResponse(
                content=content,
                usage=getattr(original_response, "usage", None),
                metadata=merged_metadata,
            )
            return new_response

        # If it's a raw dict/string, return the replacement content
        return replacement_content

    def _is_response_complete(self, response: Any) -> bool:
        """Check if the response is complete (valid for tool call processing)."""
        metadata = getattr(response, "metadata", None)
        if isinstance(metadata, dict):
            if metadata.get("is_done"):
                return True
            finish_reason = metadata.get("finish_reason")
            if finish_reason:
                return True

        # Check choices for OpenAI format
        choices = getattr(response, "choices", [])
        if isinstance(choices, list):
            for choice in choices:
                if getattr(choice, "finish_reason", None):
                    return True
                if isinstance(choice, dict) and choice.get("finish_reason"):
                    return True

        return False

    def _resolve_stream_key(
        self, session_id: str, context: dict[str, Any], response: Any
    ) -> str:
        stream_id: str | None = None
        if isinstance(context, dict):
            candidate = context.get("stream_id") or context.get("response_stream_id")
            if isinstance(candidate, str) and candidate:
                stream_id = candidate

        metadata = getattr(response, "metadata", None)
        if not stream_id and isinstance(metadata, dict):
            candidate = metadata.get("stream_id") or metadata.get("id")
            if isinstance(candidate, str) and candidate:
                stream_id = candidate

        if stream_id:
            return stream_id
        if session_id:
            return session_id
        return "anonymous-stream"

    def _reset_stream_state_if_needed(
        self, stream_key: str, response: Any, is_streaming: bool
    ) -> None:
        if self._should_reset_stream_state(response, is_streaming):
            self._clear_stream_state(stream_key)

    def _should_reset_stream_state(self, response: Any, is_streaming: bool) -> bool:
        metadata = getattr(response, "metadata", None)
        if isinstance(metadata, dict):
            if metadata.get("is_done"):
                return True
            # In streaming, we should only reset when explicitly done (is_done).
            # Resetting on finish_reason causes state loss while the stream object
            # might still be alive or retried, breaking deduplication.
            if not is_streaming:
                finish_reason = metadata.get("finish_reason")
                if finish_reason in {"stop", "length", "tool_calls"}:
                    return True
        return not is_streaming

    def _clear_stream_state(self, stream_key: str) -> None:
        self._lifecycle.clear_stream(stream_key)

    def _mark_tool_call_processed(
        self,
        tool_call: dict[str, Any],
        raw_tool_call: Any,
        stream_key: str,
        signature: str,
        buffer_state: ToolCallBufferState | None = None,
    ) -> None:
        tool_call[_TOOL_CALL_PROCESSING_MARKER] = True
        if raw_tool_call is not tool_call:
            if isinstance(raw_tool_call, dict):
                raw_tool_call[_TOOL_CALL_PROCESSING_MARKER] = True
            else:
                setattr(raw_tool_call, _TOOL_CALL_PROCESSING_MARKER, True)

        self._lifecycle.mark_processed(stream_key, signature)
        if buffer_state is not None:
            buffer_state.processed_signatures.add(signature)
