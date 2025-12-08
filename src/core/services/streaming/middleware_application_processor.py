import logging

from src.core.domain.streaming_response_processor import (
    IStreamProcessor,
    StreamingContent,
)
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.response_processor_interface import (
    IResponseFeature,
    IResponseMiddleware,
    ProcessedResponse,
)
from src.core.services.streaming.stream_context_registry import (
    StreamContextState,
    StreamingContextRegistry,
)
from src.core.services.streaming.stream_utils import get_stream_id

logger = logging.getLogger(__name__)


class MiddlewareApplicationProcessor(IStreamProcessor):
    """
    Stream processor that applies a chain of IResponseMiddleware to StreamingContent.
    """

    def __init__(
        self,
        middleware: list[IResponseFeature | IResponseMiddleware],
        default_loop_config: object | None = None,
        app_state: IApplicationState | None = None,
        registry: StreamingContextRegistry | None = None,
    ) -> None:
        def _priority(mw: IResponseFeature | IResponseMiddleware) -> int:
            try:
                p = getattr(mw, "priority", 0)
                return p if isinstance(p, int) else 0
            except (AttributeError, TypeError):
                return 0

        self._middleware = sorted(middleware, key=_priority, reverse=True)
        self._default_loop_config = default_loop_config
        self._app_state = app_state
        self._registry = registry

    async def process(self, content: StreamingContent) -> StreamingContent:
        processed_response = ProcessedResponse(
            content=content.content, usage=content.usage, metadata=content.metadata
        )
        stream_id = get_stream_id(content)
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
            "stream_id": stream_id,
        }
        original_request = content.metadata.get("original_request")
        if original_request is not None:
            context["original_request"] = original_request
            # Extract calling_agent from original_request if available
            agent = getattr(original_request, "agent", None)
            if agent:
                context["calling_agent"] = agent

        # Extract backend_name and model_name from metadata if available
        if "backend_name" in content.metadata:
            context["backend_name"] = content.metadata["backend_name"]
        if "model_name" in content.metadata:
            context["model_name"] = content.metadata["model_name"]
        # Also check for calling_agent directly in metadata
        if "calling_agent" in content.metadata and "calling_agent" not in context:
            context["calling_agent"] = content.metadata["calling_agent"]

        # Per-route flags
        if "expected_json" in content.metadata:
            context["expected_json"] = bool(content.metadata.get("expected_json"))
        if self._default_loop_config is not None:
            context["config"] = self._default_loop_config

        if self._registry is not None:
            stream_state: StreamContextState = self._registry.get_stream_state(
                stream_id
            )
            context["stream_context_state"] = stream_state
            context["tool_call_buffer_state"] = stream_state.tool_calls

        for mw in self._middleware:
            result = await mw.process(
                processed_response, session_id_str, context, is_streaming=True
            )
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
