"""
VTC wrapper builder for Gemini connectors.

This module provides the GeminiVtcWrapperBuilder class that builds optional
VTC (Virtual Tool Calling) streaming wrappers when enabled.
"""

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, cast

from src.connectors.gemini_base.interfaces import IVtcWrapperBuilder
from src.connectors.gemini_base.orchestrator import StreamWrapper
from src.core.interfaces.response_processor_interface import ProcessedResponse

if TYPE_CHECKING:
    from src.core.domain.chat import CanonicalChatRequest

logger = logging.getLogger(__name__)


class GeminiVtcWrapperBuilder(IVtcWrapperBuilder):
    """Builds optional VTC streaming wrappers for Gemini connectors.

    This builder resolves optional tool-call services via DI and constructs
    StreamWrapper instances when VTC is enabled. It returns None when VTC is
    disabled. When VTC is enabled but dependencies are unavailable, it returns
    a wrapper with None services (fail-open pattern), allowing the wrapper
    to handle missing services gracefully.
    """

    def __init__(self, *, backend_type: str = "gemini-oauth") -> None:
        """Initialize the VTC wrapper builder.

        Args:
            backend_type: The backend type identifier for reactor context.
        """
        self._backend_type = backend_type

    def build(
        self,
        request_data: "CanonicalChatRequest",
        *,
        effective_model: str,
    ) -> StreamWrapper | None:
        """Return a wrapper when VTC is enabled, otherwise None.

        Args:
            request_data: The canonical chat request.
            effective_model: The model name being used.

        Returns:
            StreamWrapper function if VTC is enabled (may have None services
            if dependencies unavailable), None if VTC is disabled.
        """
        vtc_enabled = getattr(request_data, "vtc_enabled", False) or False
        if not vtc_enabled:
            return None

        tool_call_reactor = None
        arguments_parser = None
        arguments_fixup_pipeline = None
        try:
            from src.core.di.services import get_service_provider
            from src.core.interfaces.tool_arguments_fixup_pipeline_interface import (
                IToolArgumentsFixupPipeline,
            )
            from src.core.interfaces.tool_arguments_parser_interface import (
                IToolArgumentsParser,
            )
            from src.core.services.tool_call_reactor_service import (
                ToolCallReactorService,
            )

            provider = get_service_provider()
            tool_call_reactor = provider.get_service(ToolCallReactorService)
            arguments_parser = provider.get_service(IToolArgumentsParser)  # type: ignore[type-abstract]
            arguments_fixup_pipeline = provider.get_service(IToolArgumentsFixupPipeline)  # type: ignore[type-abstract]
        except Exception as exc:
            logger.warning("Failed to get tool call reactor services for VTC: %s", exc)

        reactor_context = {
            "backend_name": self._backend_type,
            "model_name": effective_model,
            "calling_agent": getattr(request_data, "agent", None),
            "client_os": getattr(request_data, "client_os", None),
        }
        session_id = getattr(request_data, "session_id", None)

        from src.core.services.streaming.vtc_response_wrapper import (
            wrap_processed_response_stream_with_vtc,
        )

        def wrapper(
            generator: AsyncIterator[ProcessedResponse],
        ) -> AsyncIterator[ProcessedResponse]:
            return wrap_processed_response_stream_with_vtc(
                generator,
                vtc_enabled=vtc_enabled,
                tool_call_reactor=tool_call_reactor,
                arguments_parser=arguments_parser,
                arguments_fixup_pipeline=arguments_fixup_pipeline,
                session_id=session_id,
                context=reactor_context,
            )

        return cast(StreamWrapper, wrapper)


__all__ = ["GeminiVtcWrapperBuilder"]
