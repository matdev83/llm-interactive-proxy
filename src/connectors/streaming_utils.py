from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from typing import Any

from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)


async def _ensure_async_iterator(it: Any) -> AsyncIterator[bytes]:
    # Normalize different shapes into an async iterator of bytes
    if hasattr(it, "__aiter__"):
        async for chunk in it:  # type: ignore[misc]
            yield chunk
        return

    if hasattr(it, "__iter__"):
        for chunk in it:  # type: ignore[misc]
            yield chunk
        return

    if asyncio.iscoroutine(it):
        res = await it  # type: ignore[arg-type]
        if hasattr(res, "__aiter__"):
            async for chunk in res:  # type: ignore[misc]
                yield chunk
            return
        if hasattr(res, "__iter__"):
            for chunk in res:  # type: ignore[misc]
                yield chunk
            return

    # Fallback: empty
    return


def to_streaming_response(
    iterator_supplier: Callable[[], AsyncGenerator[bytes, None]],
    media_type: str = "text/event-stream",
    headers: dict[str, str] | None = None,
) -> StreamingResponse:
    """Wrap an async generator supplier into a Starlette StreamingResponse.

    The supplier should be a zero-arg callable returning an async generator.
    This helper ensures consistent StreamingResponse creation across connectors.
    """

    return StreamingResponse(
        iterator_supplier(), media_type=media_type, headers=headers
    )
