"""
Tool Call Reactor Middleware.

This middleware integrates the tool call reactor system into the response processing pipeline.
It detects tool calls in LLM responses and passes them through registered handlers.
"""

from __future__ import annotations

from typing import Any

from src.core.common.logging_utils import get_logger
from src.core.interfaces.response_processor_interface import (
    IResponseFeature,
    IResponseMiddleware,
    ProcessedResponse,
)
from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallReactor,
)
from src.core.interfaces.tool_call_reactor_orchestrator_interface import (
    IToolCallReactorOrchestrator,
    ToolCallReactorContext,
)
from src.core.interfaces.tool_call_stream_context_resolver_interface import (
    IToolCallStreamContextResolver,
)

logger = get_logger(__name__)


class ToolCallReactorFeature(IResponseFeature):
    """Feature to process tool calls with enforced streaming/non-streaming parity.

    This feature detects tool calls in LLM responses and passes them through
    the tool call reactor system, allowing handlers to react to tool calls.
    """

    def __init__(
        self,
        orchestrator: IToolCallReactorOrchestrator,
        stream_context_resolver: IToolCallStreamContextResolver,
        tool_call_reactor: IToolCallReactor,
        enabled: bool = True,
        priority: int = -10,
    ):
        """Initialize the tool call reactor feature.

        Args:
            orchestrator: The orchestrator that coordinates tool-call processing.
            stream_context_resolver: Resolver for stream context and buffer state.
            tool_call_reactor: The reactor service (for get_registered_handlers).
            enabled: Whether the feature is enabled.
            priority: Feature priority.
        """
        super().__init__(priority)
        self._orchestrator = orchestrator
        self._stream_context_resolver = stream_context_resolver
        self._tool_call_reactor = tool_call_reactor
        self._enabled = enabled

    async def _process_response(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
        is_streaming: bool,
    ) -> Any:
        """Shared processing logic for both streaming and non-streaming."""
        # Bypass check: feature disabled or bypass flag
        if not self._enabled or context.get("bypass_tool_call_reactor"):
            return response

        # Convert response to ProcessedResponse if needed
        if not isinstance(response, ProcessedResponse):
            # If response has tool_calls but content is None/empty, use response itself as content
            # This ensures tool calls are preserved for extraction
            response_content = getattr(response, "content", response)
            if (
                hasattr(response, "tool_calls")
                and response.tool_calls
                and (response_content is None or response_content == "")
            ):
                response_content = response
            response = ProcessedResponse(
                content=response_content,
                usage=getattr(response, "usage", None),
                metadata=getattr(response, "metadata", {}),
            )

        # Build ToolCallReactorContext from legacy context dict
        stream_key = self._stream_context_resolver.resolve_stream_key(
            session_id, context, response
        )
        buffer_state = self._stream_context_resolver.resolve_buffer_state(
            context, stream_key
        )

        reactor_context = ToolCallReactorContext(
            client_os=context.get("client_os") if context else None,
            stream_key=stream_key,
            buffer_state=buffer_state,
        )

        # Delegate to orchestrator
        result = await self._orchestrator.handle(
            response, session_id, reactor_context, is_streaming
        )

        return result

    async def process_non_streaming(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any],
    ) -> Any:
        """Process non-streaming response for tool calls."""
        return await self._process_response(
            response, session_id, context, is_streaming=False
        )

    async def process_streaming(
        self,
        chunk: Any,
        session_id: str,
        context: dict[str, Any],
    ) -> Any:
        """Process streaming chunk for tool calls."""
        return await self._process_response(
            chunk, session_id, context, is_streaming=True
        )

    def get_registered_handlers(self) -> list[str]:
        """Get the names of all registered handlers."""
        return self._tool_call_reactor.get_registered_handlers()

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the feature."""
        self._enabled = enabled


# Legacy middleware kept for backward compatibility during transition
# DEPRECATED: Use ToolCallReactorFeature instead
class ToolCallReactorMiddleware(IResponseMiddleware):
    """DEPRECATED: Use ToolCallReactorFeature instead.

    Legacy middleware that integrates tool call reactor into the response pipeline.
    This class is kept for backward compatibility only.
    """

    def __init__(
        self,
        orchestrator: IToolCallReactorOrchestrator,
        stream_context_resolver: IToolCallStreamContextResolver,
        tool_call_reactor: IToolCallReactor,
        enabled: bool = True,
        priority: int = -10,
    ):
        """Initialize the tool call reactor middleware.

        Args:
            orchestrator: The orchestrator that coordinates tool-call processing.
            stream_context_resolver: Resolver for stream context and buffer state.
            tool_call_reactor: The reactor service (for get_registered_handlers).
            enabled: Whether middleware is enabled.
            priority: Priority of this middleware (lower numbers run later).
        """
        logger.warning(
            "DEPRECATED: ToolCallReactorMiddleware instantiated. "
            "Use ToolCallReactorFeature instead for proper streaming/non-streaming parity."
        )
        self._orchestrator = orchestrator
        self._stream_context_resolver = stream_context_resolver
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
            stop_event: Optional stop event for streaming (ignored)

        Returns:
            The processed response (potentially modified by handlers)
        """
        # Bypass check: middleware disabled or bypass flag
        if not self._enabled or context.get("bypass_tool_call_reactor"):
            return response

        # Convert response to ProcessedResponse if needed
        if not isinstance(response, ProcessedResponse):
            # If response has tool_calls but content is None/empty, use response itself as content
            # This ensures tool calls are preserved for extraction
            response_content = getattr(response, "content", response)
            if (
                hasattr(response, "tool_calls")
                and response.tool_calls
                and (response_content is None or response_content == "")
            ):
                response_content = response
            response = ProcessedResponse(
                content=response_content,
                usage=getattr(response, "usage", None),
                metadata=getattr(response, "metadata", {}),
            )

        # Build ToolCallReactorContext from legacy context dict
        stream_key = self._stream_context_resolver.resolve_stream_key(
            session_id, context, response
        )
        buffer_state = self._stream_context_resolver.resolve_buffer_state(
            context, stream_key
        )

        reactor_context = ToolCallReactorContext(
            client_os=context.get("client_os") if context else None,
            stream_key=stream_key,
            buffer_state=buffer_state,
        )

        # Delegate to orchestrator
        result = await self._orchestrator.handle(
            response, session_id, reactor_context, is_streaming
        )

        return result

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
