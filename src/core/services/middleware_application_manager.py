from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from src.core.interfaces.middleware_application_manager_interface import (
    IMiddlewareApplicationManager,
)
from src.core.interfaces.response_processor_interface import (
    IResponseFeature,
    IResponseMiddleware,
    ProcessedResponse,
)

logger = logging.getLogger(__name__)

# Type alias for middleware/features - both are supported
ResponseProcessor = IResponseFeature | IResponseMiddleware


class MiddlewareApplicationManager(IMiddlewareApplicationManager):
    """
    Orchestrates the application of response features/middleware.

    This manager supports both IResponseFeature (preferred, with explicit
    streaming/non-streaming methods) and legacy IResponseMiddleware.
    """

    def __init__(self, middleware: list[ResponseProcessor]) -> None:
        def _priority(mw: ResponseProcessor) -> int:
            try:
                p = getattr(mw, "priority", 0)
                return p if isinstance(p, int) else 0
            except (AttributeError, TypeError):
                return 0

        self._middleware = sorted(middleware, key=_priority, reverse=True)

    async def apply_middleware(
        self,
        content: Any,
        middleware_list: list[ResponseProcessor] | None = None,
        is_streaming: bool = False,
        stop_event: Any = None,
        session_id: str = "",
        context: dict[str, Any] | None = None,
    ) -> Any:
        """
        Applies a list of response features/middleware to the given content.

        Supports both IResponseFeature (with explicit streaming/non-streaming methods)
        and legacy IResponseMiddleware. Features are preferred and will use the
        explicit methods for better parity enforcement.

        Args:
            content: The content to apply features/middleware to.
            middleware_list: A list of features/middleware to apply.
            is_streaming: Whether this is a streaming response.
            stop_event: Optional event to signal early termination.
            session_id: The session identifier.
            context: Additional context for processing.

        Returns:
            The content after applying all features/middleware.
        """
        middleware_to_apply = (
            middleware_list if middleware_list is not None else self._middleware
        )

        if is_streaming:
            return await self._apply_streaming_middleware(
                content,
                middleware_to_apply,
                stop_event,
                session_id,
                context,
            )

        return await self._apply_non_streaming_middleware(
            content,
            middleware_to_apply,
            stop_event,
            session_id,
            context,
        )

    async def _apply_non_streaming_middleware(
        self,
        content: Any,
        middleware_list: list[ResponseProcessor],
        stop_event: Any = None,
        session_id: str = "",
        context: dict[str, Any] | None = None,
    ) -> Any:
        processed_response = ProcessedResponse(content=content, usage=None, metadata={})

        base_context: dict[str, Any] = {"stop_event": stop_event}
        if context:
            base_context.update(context)

        for mw in middleware_list:
            try:
                middleware_context = dict(base_context)
                # Prefer explicit non-streaming method if available (IResponseFeature)
                if isinstance(mw, IResponseFeature):
                    result = await mw.process_non_streaming(
                        processed_response,
                        session_id,
                        middleware_context,
                    )
                else:
                    # Legacy IResponseMiddleware fallback
                    result = await mw.process(
                        processed_response,
                        session_id,
                        middleware_context,
                        is_streaming=False,
                        stop_event=stop_event,
                    )
                if result is not None:
                    processed_response = result
            except Exception as e:
                logger.error(
                    "Error applying middleware %s: %s",
                    mw.__class__.__name__,
                    e,
                    exc_info=True,
                )
        content_value = processed_response.content
        if content_value is None:
            return ""
        return content_value

    async def _apply_streaming_middleware(
        self,
        content_iterator: Any,
        middleware_list: list[ResponseProcessor],
        stop_event: Any,
        session_id: str = "",
        context: dict[str, Any] | None = None,
    ) -> Any:
        base_context: dict[str, Any] = {"stop_event": stop_event}
        if context:
            base_context.update(context)

        async def generator() -> AsyncGenerator[Any, None]:
            if stop_event and stop_event.is_set():
                return
            async for chunk in content_iterator:
                if stop_event and stop_event.is_set():
                    break
                processed_chunk = chunk
                for mw in middleware_list:
                    try:
                        middleware_context = dict(base_context)
                        # Prefer explicit streaming method if available (IResponseFeature)
                        if isinstance(mw, IResponseFeature):
                            result = await mw.process_streaming(
                                processed_chunk,
                                session_id,
                                middleware_context,
                            )
                        else:
                            # Legacy IResponseMiddleware fallback
                            result = await mw.process(
                                processed_chunk,
                                session_id,
                                middleware_context,
                                is_streaming=True,
                                stop_event=stop_event,
                            )
                        if result is not None:
                            processed_chunk = result
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Middleware %s returned chunk (is_none=%s) for session=%s",
                                mw.__class__.__name__,
                                result is None,
                                session_id,
                            )
                    except Exception as e:
                        logger.error(
                            "Error applying streaming middleware %s: %s",
                            mw.__class__.__name__,
                            e,
                            exc_info=True,
                        )
                yield processed_chunk

        return generator()
