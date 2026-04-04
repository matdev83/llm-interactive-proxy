"""
Kiro stream normalizer.

The Kiro connector emits `StreamingContent` objects directly. This normalizer
simply validates and forwards them into the streaming pipeline so we can reuse
middleware (tool call repair, loop detection, think tags, etc.) and the SSE
assembler.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from src.core.domain.streaming.streaming_content import StreamingContent
from src.core.ports.streaming.normalizer_base import BaseStreamNormalizer
from src.core.services.streaming.error_mapping import handle_streaming_error

logger = logging.getLogger(__name__)


class KiroStreamNormalizer(BaseStreamNormalizer):
    def __init__(self) -> None:
        super().__init__(provider="kiro")

    async def normalize_stream(
        self, stream: AsyncIterator[object], provider: str
    ) -> AsyncIterator[StreamingContent]:
        stream_id: str | None = None
        emitted_any = False
        try:
            async for raw_chunk in stream:
                if not isinstance(raw_chunk, StreamingContent):
                    logger.warning(
                        "Skipping non-StreamingContent chunk",
                        extra={
                            "provider": self.provider,
                            "type": type(raw_chunk).__name__,
                        },
                    )
                    continue
                if not self.validate_chunk(raw_chunk):
                    logger.warning(
                        "Dropping invalid Kiro chunk",
                        extra={
                            "provider": self.provider,
                            "stream_id": raw_chunk.stream_id,
                        },
                    )
                    continue
                if stream_id is None and raw_chunk.stream_id:
                    stream_id = raw_chunk.stream_id
                raw_chunk.metadata.setdefault("provider", self.provider)
                emitted_any = True
                yield raw_chunk
        except Exception as exc:
            if not emitted_any:
                raise
            error_chunk = await handle_streaming_error(exc, stream_id, self.provider)
            yield error_chunk
