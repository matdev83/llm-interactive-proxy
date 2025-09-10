from __future__ import annotations

import logging

from src.core.domain.chat import StreamingChatResponse
from src.core.domain.streaming_content import StreamingContent
from src.core.domain.streaming_data_parsers.raw_data_parser import IRawDataParser

logger = logging.getLogger(__name__)


class StreamingChatResponseParser(IRawDataParser):
    """Parses domain StreamingChatResponse objects into StreamingContent."""

    def parse(self, data: StreamingChatResponse) -> StreamingContent:
        content = data.content if data.content is not None else ""
        metadata = {
            "id": getattr(data, "id", ""),
            "model": getattr(data, "model", "unknown"),
            "created": getattr(data, "created", 0),
        }

        # The StreamingChatResponse object itself should already have the content
        # extracted, so we directly use data.content.
        # If tool_calls are present, they should be part of the metadata or handled separately
        # by the streaming content processor, not directly used to extract content here.

        usage = getattr(data, "usage", None)

        return StreamingContent(
            content=content,
            metadata=metadata,
            usage=usage,
            raw_data=data.model_dump(),  # Convert the Pydantic model to a dictionary
        )
