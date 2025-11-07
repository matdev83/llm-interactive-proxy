from __future__ import annotations

import asyncio

import pytest
from src.core.app.middleware.content_rewriting_middleware import (
    ContentRewritingMiddleware,
)
from src.core.domain.replacement_rule import ReplacementMode, ReplacementRule
from src.core.services.content_rewriter_service import ContentRewriterService
from starlette.requests import Request
from starlette.responses import StreamingResponse


def _build_request() -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
        "scheme": "http",
        "http_version": "1.1",
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


@pytest.mark.asyncio
async def test_streaming_rewrite_preserves_streaming_and_cross_chunk_matches() -> None:
    rewriter = ContentRewriterService(config_path="non-existent")
    rewriter.reply_rules = [
        ReplacementRule(
            mode=ReplacementMode.REPLACE,
            search="HELLO",
            replace="BYE",
        )
    ]
    rewriter.refresh_rule_cache()

    middleware = ContentRewritingMiddleware(lambda request: None, rewriter)
    request = _build_request()

    chunks = [b"start HEL", b"LO mid HEL", b"LO end"]
    chunk_iterated: list[bytes] = []

    async def chunk_generator():
        for chunk in chunks:
            chunk_iterated.append(chunk)
            yield chunk
            await asyncio.sleep(0)

    async def call_next(_request: Request) -> StreamingResponse:
        return StreamingResponse(chunk_generator(), media_type="text/plain")

    response = await middleware.dispatch(request, call_next)

    # Nothing has been consumed yet.
    assert not chunk_iterated

    body_iter = response.body_iterator
    assert body_iter is not None

    collected = b""
    try:
        while True:
            collected += await body_iter.__anext__()
    except StopAsyncIteration:
        pass

    # All chunks were produced lazily during iteration.
    assert chunk_iterated == chunks

    assert collected.decode("utf-8") == "start BYE mid BYE end"
