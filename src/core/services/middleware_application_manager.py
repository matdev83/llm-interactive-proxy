from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from src.core.interfaces.middleware_application_manager_interface import (
    IMiddlewareApplicationManager,
)
from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
    ProcessedResponse,
)

logger = logging.getLogger(__name__)


class MiddlewareApplicationManager(IMiddlewareApplicationManager):
    """
    Orchestrates the application of response middleware for non-streaming responses.
    """

    def __init__(self, middleware: list[IResponseMiddleware]) -> None:
        def _priority(mw: IResponseMiddleware) -> int:
            try:
                p = getattr(mw, "priority", 0)
                return p if isinstance(p, int) else 0
            except (AttributeError, TypeError):
                return 0

        self._middleware = sorted(middleware, key=_priority, reverse=True)

    async def apply_middleware(
        self,
        content: Any,
        middleware_list: list[IResponseMiddleware] | None = None,
        is_streaming: bool = False,
        stop_event: Any = None,
        session_id: str = "",
        context: dict[str, Any] | None = None,
    ) -> Any:
        """
        Applies a list of response middleware to the given content.
        If middleware_list is provided, it is used. Otherwise, the middleware
        from the constructor is used.
        Args:
            content: The content to apply middleware to.
            middleware_list: A list of IResponseMiddleware objects to apply.
            is_streaming: A boolean indicating if the middleware is applied during streaming.
            stop_event: An optional event to signal early termination during streaming.
        Returns:
            The content after applying all middleware. For streaming, this might be a generator.
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
        middleware_list: list[IResponseMiddleware],
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
                    f"Error applying middleware {mw.__class__.__name__}: {e}",
                    exc_info=True,
                )
        content_value = processed_response.content
        if content_value is None:
            return ""
        return content_value

    async def _apply_streaming_middleware(
        self,
        content_iterator: Any,
        middleware_list: list[IResponseMiddleware],
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
                        result = await mw.process(
                            processed_chunk,
                            session_id,
                            middleware_context,
                            is_streaming=True,
                            stop_event=stop_event,
                        )
                        if result is not None:
                            processed_chunk = result
                    except Exception as e:
                        logger.error(
                            f"Error applying streaming middleware {mw.__class__.__name__}: {e}",
                            exc_info=True,
                        )
                yield processed_chunk

        return generator()
