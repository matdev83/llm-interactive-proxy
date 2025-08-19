from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from starlette.responses import JSONResponse, Response, StreamingResponse

from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope


def to_fastapi_response(envelope: ResponseEnvelope) -> Response:
    """Convert a domain ResponseEnvelope to a FastAPI Response."""
    return JSONResponse(
        content=envelope.content,
        status_code=envelope.status_code,
        headers=envelope.headers,
    )


def to_fastapi_streaming_response(
    envelope: StreamingResponseEnvelope,
) -> StreamingResponse:
    """Convert a domain StreamingResponseEnvelope to a FastAPI StreamingResponse."""
    return StreamingResponse(
        content=envelope.content,
        media_type=envelope.media_type,
        headers=envelope.headers,
    )


def adapt_response(
    response: ResponseEnvelope | StreamingResponseEnvelope | Response,
) -> Response:
    """Adapt any response type to a FastAPI Response.

    This is useful in controllers that need to handle multiple response types.
    """
    if isinstance(response, ResponseEnvelope):
        return to_fastapi_response(response)
    elif isinstance(response, StreamingResponseEnvelope):
        return to_fastapi_streaming_response(response)
    elif isinstance(response, Response):
        return response
    else:
        raise TypeError(f"Unexpected response type: {type(response)}")


async def wrap_async_iterator(
    source: AsyncIterator[bytes], mapper: Callable[[bytes], bytes] | None = None
) -> AsyncIterator[bytes]:
    """Wrap an async iterator with an optional mapping function.

    Args:
        source: Source async iterator
        mapper: Optional function to transform each chunk

    Yields:
        Transformed chunks from the source iterator
    """
    async for chunk in source:
        if mapper:
            yield mapper(chunk)
        else:
            yield chunk
