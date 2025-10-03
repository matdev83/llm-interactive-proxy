import logging

from src.core.domain.streaming_response_processor import (
    IStreamProcessor,
    StreamingContent,
)

logger = logging.getLogger(__name__)


class ContentAccumulationProcessor(IStreamProcessor):
    """
    Stream processor that accumulates content from streaming chunks.
    """

    def __init__(self) -> None:
        self._buffer = ""

    async def process(self, content: StreamingContent) -> StreamingContent:
        if content.is_empty and not content.is_done:
            return StreamingContent(content="")

        self._buffer += content.content

        if content.is_done:
            final_content = self._buffer
            self._buffer = ""
            return StreamingContent(
                content=final_content,
                is_done=True,
                metadata=content.metadata,
                usage=content.usage,
                raw_data=content.raw_data,
            )
        else:
            return StreamingContent(
                content="",
                metadata=content.metadata,
                usage=content.usage,
                raw_data=content.raw_data,
            )
