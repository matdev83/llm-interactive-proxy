from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from src.connectors.base import LLMBackend
from src.core.app.test_builder import build_test_app, create_test_config
from src.core.domain.chat import ChatMessage
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


class _AuthenticationRequiredError(Exception):
    """Raised when the proxy requires authentication during the test."""


class ConcurrentMockBackend(LLMBackend):
    """Backend that simulates streaming responses for concurrent sessions."""

    backend_type = "openai"

    def __init__(self) -> None:
        super().__init__(config=create_test_config())
        self.active_sessions: set[str] = set()
        self.stream_history: dict[str, int] = {}

    async def chat_completions(  # type: ignore[override]
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        identity: Any | None = None,
        **kwargs: Any,
    ) -> StreamingResponseEnvelope:
        marker = "unknown-session"
        if getattr(request_data, "messages", None):
            first_message = request_data.messages[0]
            marker = getattr(first_message, "content", marker) or marker

        self.stream_history.setdefault(marker, 0)

        async def stream() -> AsyncIterator[ProcessedResponse]:
            self.active_sessions.add(marker)
            try:
                for idx in range(3):
                    await asyncio.sleep(0.01)
                    self.stream_history[marker] += 1
                    # Use proper OpenAI streaming format so stream normalizer recognizes content
                    chunk_data = {
                        "id": f"chatcmpl-{marker}-{idx}",
                        "object": "chat.completion.chunk",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": f"session:{marker},chunk:{idx}"},
                            }
                        ],
                    }
                    import json

                    yield ProcessedResponse(
                        content=f"data: {json.dumps(chunk_data)}\n\n"
                    )
                yield ProcessedResponse(content="data: [DONE]\n\n")
            finally:
                # Ensure cleanup happens even if generator is cancelled
                await asyncio.sleep(0)  # Yield control to allow cleanup
                self.active_sessions.discard(marker)

        return StreamingResponseEnvelope(
            content=stream(),
            media_type="text/event-stream",
            headers={"content-type": "text/event-stream"},
        )

    async def initialize(self, **kwargs: Any) -> None:  # pragma: no cover - trivial
        return None

    def get_available_models(self) -> list[str]:  # pragma: no cover - trivial
        return ["test-model"]


def _inject_backend(app, backend: ConcurrentMockBackend) -> None:
    """Replace the OpenAI backend with our concurrent mock backend."""
    service_provider = app.state.service_provider
    from src.core.interfaces.backend_service_interface import IBackendService

    backend_service = service_provider.get_required_service(IBackendService)
    backend_service._backends["openai"] = backend

    async def call_completion_override(
        request: Any,
        stream: bool = False,
        allow_failover: bool = True,
        context: Any | None = None,
    ) -> StreamingResponseEnvelope:
        request_stream = stream or getattr(request, "stream", False)
        if not request_stream:
            raise AssertionError("ConcurrentMockBackend expects streaming requests")
        return await backend.chat_completions(
            request_data=request,
            processed_messages=[],
            effective_model=getattr(request, "model", "gpt-4"),
            identity=None,
        )

    backend_service.call_completion = call_completion_override  # type: ignore[attr-defined]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_parallel_streaming_requests_isolate_sessions() -> None:
    backend = ConcurrentMockBackend()
    # Disable loop detection since mock backend produces similar patterns
    from src.core.app.test_builder import create_test_config

    base_config = create_test_config()
    # Use model_copy since pydantic models are frozen
    session_with_loop_disabled = base_config.session.model_copy(
        update={"loop_detection_enabled": False}
    )
    config = base_config.model_copy(update={"session": session_with_loop_disabled})
    app = build_test_app(config)
    app.state.disable_auth = True  # type: ignore[attr-defined]
    _inject_backend(app, backend)

    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")

    async def run_session(label: str) -> list[str]:
        payload = {
            "model": "gpt-4",
            "messages": [ChatMessage(role="user", content=label).model_dump()],
            "stream": True,
        }
        headers = {"x-goog-api-key": "test-proxy-key"}

        async with client.stream(
            "POST", "/v1/chat/completions", json=payload, headers=headers
        ) as response:
            if response.status_code == 401:
                raise _AuthenticationRequiredError
            assert response.status_code == 200

            chunks: list[str] = []
            async for chunk in response.aiter_text():
                text = chunk.strip()
                if text:
                    chunks.append(text)
            # Ensure stream is fully consumed and generator is closed
            await asyncio.sleep(0.05)
            return chunks

    try:
        alpha_chunks, beta_chunks = await asyncio.gather(
            run_session("session-alpha"),
            run_session("session-beta"),
        )
    except _AuthenticationRequiredError:
        pytest.skip("Authentication required, skipping concurrent streaming test")
    finally:
        await client.aclose()
        await transport.aclose()

    # Give streams time to fully complete and cleanup
    # The finally blocks in async generators execute when the generator is closed
    await asyncio.sleep(0.2)

    # Sessions should be cleaned up after streams complete
    assert backend.active_sessions == set(), f"Expected no active sessions, but found: {backend.active_sessions}"
    assert backend.stream_history["session-alpha"] == 3
    assert backend.stream_history["session-beta"] == 3

    alpha_data = [chunk for chunk in alpha_chunks if "session-alpha" in chunk]
    beta_data = [chunk for chunk in beta_chunks if "session-beta" in chunk]

    assert all("session-alpha" in chunk for chunk in alpha_data)
    assert all("session-beta" in chunk for chunk in beta_data)
    assert not any("session-beta" in chunk for chunk in alpha_data)
    assert not any("session-alpha" in chunk for chunk in beta_data)
