from __future__ import annotations

from fastapi import FastAPI
from starlette.responses import StreamingResponse
from starlette.testclient import TestClient

from src.core.app.middleware.content_rewriting_middleware import (
    ContentRewritingMiddleware,
)


class DummyRewriter:
    """Simple stand-in for ``ContentRewriterService`` used in tests."""

    def __init__(self) -> None:
        self.rewrite_calls: list[str] = []

    def rewrite_prompt(
        self, prompt: str, prompt_type: str
    ) -> str:  # pragma: no cover - unused
        return prompt

    def rewrite_reply(self, reply: str) -> str:
        self.rewrite_calls.append(reply)
        return reply.replace("foo", "bar")


def _create_streaming_app(rewriter: DummyRewriter) -> TestClient:
    app = FastAPI()

    @app.get("/stream")
    async def stream_endpoint() -> StreamingResponse:
        async def generator():
            yield b"foo"
            yield b"foo"

        return StreamingResponse(generator(), media_type="text/plain")

    app.add_middleware(ContentRewritingMiddleware, rewriter=rewriter)
    return TestClient(app)


def test_streaming_rewrite_within_limit(monkeypatch):
    monkeypatch.setattr(ContentRewritingMiddleware, "_MAX_STREAM_REWRITE_BYTES", 1024)
    rewriter = DummyRewriter()
    client = _create_streaming_app(rewriter)

    response = client.get("/stream")

    assert response.status_code == 200
    assert response.text == "barbar"
    assert rewriter.rewrite_calls == ["foofoo"]


def test_streaming_rewrite_skips_when_limit_exceeded(monkeypatch):
    monkeypatch.setattr(ContentRewritingMiddleware, "_MAX_STREAM_REWRITE_BYTES", 4)
    rewriter = DummyRewriter()
    client = _create_streaming_app(rewriter)

    response = client.get("/stream")

    assert response.status_code == 200
    assert response.text == "foofoo"
    assert rewriter.rewrite_calls == []
