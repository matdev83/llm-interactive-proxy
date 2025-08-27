from __future__ import annotations

import json
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from src.connectors.base import LLMBackend
from src.core.app.test_builder import build_test_app
from src.core.domain.chat import ChatMessage
from src.core.domain.responses import StreamingResponseEnvelope

from tests.unit.openai_connector_tests.test_streaming_response import AsyncIterBytes


class MockBackend(LLMBackend):
    def __init__(self, response_chunks: list[bytes]):
        self.response_chunks = response_chunks
        from src.core.app.test_builder import create_test_config
        from src.core.config.app_config import AppConfig

        # Create a minimal test config to satisfy base class
        config: AppConfig = create_test_config()
        super().__init__(config=config)

    async def chat_completions(
        self,
        request_data: Any,
        processed_messages: list,
        effective_model: str,
        identity: Any = None,
        **kwargs,
    ):
        # Check if streaming is requested
        stream = (
            getattr(request_data, "stream", False)
            if hasattr(request_data, "stream")
            else False
        )

        if stream:
            # Return a streaming response envelope with our fragmented JSON
            return StreamingResponseEnvelope(
                content=AsyncIterBytes(self.response_chunks),
                headers={"content-type": "text/event-stream"},
            )
        else:
            # For non-streaming, return a simple response
            from src.core.domain.responses import ResponseEnvelope

            return ResponseEnvelope(
                content={"test": "response"},
                headers={"content-type": "application/json"},
            )

    def get_available_models(self) -> list[str]:
        return ["test-model"]

    async def initialize(self, **kwargs) -> None:
        pass


@pytest.mark.asyncio
async def test_streaming_json_repair_with_mock_backend(monkeypatch) -> None:
    """Test that the middleware correctly repairs fragmented streaming JSON."""

    # Simulate a backend that streams fragmented and malformed JSON
    response_chunks = [
        b"""{"key": "value", "items": [""",
        b"""{"id": 1, "name": "item1"},""",
        b"""{"id": 2, "name": "item2"}""",
        b"""]}""",
    ]

    mock_backend = MockBackend(response_chunks=response_chunks)

    # Create a function to initialize the app and then inject our mock backend
    def mock_backend_injection(app):
        # Get the backend service from the app's service provider
        service_provider = app.state.service_provider
        from src.core.interfaces.backend_service_interface import IBackendService

        backend_service = service_provider.get_required_service(IBackendService)

        # Inject our mock backend into the backend service's cache
        backend_service._backends["openai"] = mock_backend

    # Build the app and inject our mock backend
    app = build_test_app()
    mock_backend_injection(app)
    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as client,
        client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [ChatMessage(role="user", content="test").model_dump()],
                "stream": True,
            },
            headers={"x-goog-api-key": "test-proxy-key"},
        ) as response,
    ):
        assert response.status_code == 200

        # Collect the streaming response
        content = ""
        async for chunk in response.aiter_bytes():
            content += chunk.decode("utf-8")

    # The repaired stream should be valid JSON
    repaired_json = json.loads(content)
    assert repaired_json == {
        "key": "value",
        "items": [{"id": 1, "name": "item1"}, {"id": 2, "name": "item2"}],
    }
