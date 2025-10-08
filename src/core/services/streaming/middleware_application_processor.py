import logging

from src.core.domain.streaming_response_processor import (
    IStreamProcessor,
    StreamingContent,
)
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
    ProcessedResponse,
)

logger = logging.getLogger(__name__)


class MiddlewareApplicationProcessor(IStreamProcessor):
    """
    Stream processor that applies a chain of IResponseMiddleware to StreamingContent.
    """

    def __init__(
        self,
        middleware: list[IResponseMiddleware],
        default_loop_config: object | None = None,
        app_state: IApplicationState | None = None,
    ) -> None:
        def _priority(mw: IResponseMiddleware) -> int:
            try:
                p = getattr(mw, "priority", 0)
                return p if isinstance(p, int) else 0
            except (AttributeError, TypeError):
                return 0

        self._middleware = sorted(middleware, key=_priority, reverse=True)
        self._default_loop_config = default_loop_config
        self._app_state = app_state

    async def process(self, content: StreamingContent) -> StreamingContent:
        processed_response = ProcessedResponse(
            content=content.content, usage=content.usage, metadata=content.metadata
        )
        # Prefer explicit session_id; fall back to chunk id when available
        session_id_str = str(
            content.metadata.get("session_id") or content.metadata.get("id") or ""
        )
        response_type = (
            "non_streaming" if content.metadata.get("non_streaming") else "stream"
        )
        context: dict[str, object] = {
            "session_id": session_id_str,
            "response_type": response_type,
            "app_state": self._app_state,
        }
        # Per-route flags
        if "expected_json" in content.metadata:
            context["expected_json"] = bool(content.metadata.get("expected_json"))
        if self._default_loop_config is not None:
            context["config"] = self._default_loop_config

        for mw in self._middleware:
            result = await mw.process(processed_response, session_id_str, context)
            # Allow middleware to be no-op by returning None
            if result is not None:
                processed_response = result

        # Convert back to StreamingContent
        content_value = processed_response.content
        if content_value is None:
            content_value = ""

        return StreamingContent(
            content=content_value,
            is_done=content.is_done,
            is_cancellation=content.is_cancellation,
            metadata=processed_response.metadata,
            usage=processed_response.usage,
            raw_data=content.raw_data,
        )
