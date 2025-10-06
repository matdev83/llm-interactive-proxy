"""
Tool Call Reactor Middleware.

This middleware integrates the tool call reactor system into the response processing pipeline.
It detects tool calls in LLM responses and passes them through registered handlers.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from json_repair import repair_json

from src.core.domain.responses import ProcessedResponse
from src.core.interfaces.response_processor_interface import IResponseMiddleware
from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallReactor,
    ToolCallContext,
)

logger = logging.getLogger(__name__)


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
    ):
        """Initialize the tool call reactor middleware.

        Args:
            tool_call_reactor: The tool call reactor service
            enabled: Whether the middleware is enabled
            priority: Priority of this middleware (lower numbers run later)
        """
        self._tool_call_reactor = tool_call_reactor
        self._enabled = enabled
        self._priority = priority

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
        if not self._enabled:
            return response

        # Skip processing if no response content
        if not hasattr(response, "content") or not response.content:
            return response

        # Extract tool calls from metadata first, then from content as fallback
        tool_calls: list[dict[str, Any]] = []
        try:
            meta_calls = getattr(response, "metadata", {}).get("tool_calls")
            if isinstance(meta_calls, list):
                tool_calls.extend([tc for tc in meta_calls if isinstance(tc, dict)])
        except Exception as e:
            logger.debug(
                f"Error extracting tool calls from metadata: {e}", exc_info=True
            )

        if not tool_calls:
            tool_calls = self._extract_tool_calls(response.content)
        if not tool_calls:
            return response

        logger.debug(f"Detected {len(tool_calls)} tool call(s) in session {session_id}")

        # Get session context information
        backend_name = context.get("backend_name", "unknown")
        model_name = context.get("model_name", "unknown")
        calling_agent = context.get("calling_agent")

        # Expose detected tool calls in response metadata for downstream consumers
        try:
            if hasattr(response, "metadata") and isinstance(response.metadata, dict):
                response.metadata.setdefault("tool_calls", [])
                # Only extend if not already present to avoid duplication
                if response.metadata["tool_calls"] == []:
                    response.metadata["tool_calls"] = list(tool_calls)
            # Also pass via context so processors can use them even if metadata is overwritten later
            if isinstance(context, dict):
                context["detected_tool_calls"] = list(tool_calls)
        except Exception:
            logger.debug(
                "Failed to annotate tool calls in metadata/context", exc_info=True
            )

        # Process each tool call through the reactor
        for tool_call in tool_calls:
            function_payload = tool_call.get("function")

            if not isinstance(function_payload, dict):
                logger.debug(
                    "Skipping tool call with invalid function payload: %s",
                    tool_call,
                )
                continue

            # Parse tool arguments if they are a JSON string
            tool_arguments_raw = function_payload.get("arguments", {})
            tool_arguments: dict[str, Any] = {}
            if isinstance(tool_arguments_raw, str):
                try:
                    # Attempt to repair the JSON before loading
                    repaired_arguments = repair_json(tool_arguments_raw)
                    parsed_args = json.loads(repaired_arguments)
                    if isinstance(parsed_args, dict):
                        tool_arguments = parsed_args
                except (json.JSONDecodeError, TypeError):
                    # If repair fails, log it and default to an empty dict
                    logger.warning(
                        f"Could not parse tool arguments after repair: {tool_arguments_raw}",
                        exc_info=True,
                    )
            elif isinstance(tool_arguments_raw, dict):
                tool_arguments = tool_arguments_raw

            tool_context = ToolCallContext(
                session_id=session_id,
                backend_name=backend_name,
                model_name=model_name,
                full_response=response.content,
                tool_name=function_payload.get("name", "unknown"),
                tool_arguments=tool_arguments,
                calling_agent=calling_agent,
            )

            try:
                result = await self._tool_call_reactor.process_tool_call(tool_context)

                if result and result.should_swallow:
                    logger.info(
                        f"Tool call '{tool_context.tool_name}' was swallowed by reactor "
                        f"in session {session_id}"
                    )

                    # Create a new response with the replacement content
                    if result.replacement_response:
                        replacement_response = self._create_replacement_response(
                            response, result.replacement_response, tool_call
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
                # Continue with next tool call on error

        # No handlers swallowed any tool calls, return original response
        return response

    def _extract_tool_calls(self, content: Any) -> list[dict[str, Any]]:
        """Extract tool calls from response content.

        Args:
            content: The response content

        Returns:
            List of tool call dictionaries
        """
        if not content:
            return []

        # Normalize the content into a Python structure that can be inspected
        if isinstance(content, (dict, list)):
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

    def _create_replacement_response(
        self,
        original_response: Any,
        replacement_content: str,
        original_tool_call: dict[str, Any],
    ) -> Any:
        """Create a replacement response with the steering content.

        Args:
            original_response: The original response object
            replacement_content: The replacement content from the handler
            original_tool_call: The original tool call that was swallowed

        Returns:
            A new response object with the replacement content
        """
        # If the original response has a content attribute, create a new ProcessedResponse
        if hasattr(original_response, "content"):
            # Create a new ProcessedResponse with the replacement content
            new_response = ProcessedResponse(
                content=replacement_content,
                usage=getattr(original_response, "usage", None),
                metadata={
                    **getattr(original_response, "metadata", {}),
                    "tool_call_swallowed": True,
                    "original_tool_call": original_tool_call,
                    "replacement_provided": True,
                },
            )
            return new_response

        # If it's a raw dict/string, return the replacement content
        return replacement_content

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the middleware.

        Args:
            enabled: Whether to enable the middleware
        """
        self._enabled = enabled
        logger.info(
            f"Tool call reactor middleware {'enabled' if enabled else 'disabled'}"
        )

    def get_registered_handlers(self) -> list[str]:
        """Get the names of registered handlers.

        Returns:
            List of handler names
        """
        return self._tool_call_reactor.get_registered_handlers()

    async def register_handler(self, handler: Any) -> None:
        """Register a new handler with the reactor.

        Args:
            handler: The handler to register
        """
        await self._tool_call_reactor.register_handler(handler)

    async def unregister_handler(self, handler_name: str) -> None:
        """Unregister a handler from the reactor.

        Args:
            handler_name: The name of the handler to unregister
        """
        await self._tool_call_reactor.unregister_handler(handler_name)
