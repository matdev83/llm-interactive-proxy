"""Regression coverage for OpenAI streaming error status propagation.

Historically, SSE error chunks could be surfaced with HTTP 200 if integration
logic was bypassed. This test ensures the OpenAI connector streaming path keeps
provider error status (e.g., 429) on the response envelope.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
    ConnectorRequestContext,
)
from src.connectors.openai import OpenAIConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.services.translation_service import TranslationService


class _NoopServiceProvider:
    """Minimal DI provider used to keep streaming tests unit-scoped."""

    def get_service(self, _service_type: Any) -> None:
        return None

    def get_required_service(self, _service_type: Any) -> Any:
        raise AssertionError(
            "get_required_service should not be called when vtc_enabled=False"
        )


@pytest.fixture
def mock_client() -> AsyncMock:
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def mock_config() -> MagicMock:
    config = MagicMock(spec=AppConfig)
    config.streaming_yield_interval = 100
    return config


@pytest.fixture
def openai_connector(mock_client: AsyncMock, mock_config: MagicMock) -> OpenAIConnector:
    connector = OpenAIConnector(
        client=mock_client,
        config=mock_config,
        translation_service=TranslationService(),
    )
    connector.api_key = "test-api-key"
    connector.api_base_url = "https://api.openai.com/v1"
    connector.disable_health_check()
    return connector


_ERROR_STATUS_429_SSE = (
    'data: {"id":"chatcmpl-err","object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"error"}],"error":{"message":"Rate limit exceeded","type":"RateLimitExceededError","status_code":429}}\n\n'
    "data: [DONE]\n\n"
)


async def _collect_chunks(envelope: StreamingResponseEnvelope) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    async for raw_bytes in envelope.body_iterator:
        for line in raw_bytes.decode("utf-8").splitlines():
            payload = line.strip()
            if not payload.startswith("data:"):
                continue
            parsed_payload = payload[5:].strip()
            if not parsed_payload or parsed_payload == "[DONE]":
                continue
            chunks.append(json.loads(parsed_payload))
    return chunks


@pytest.mark.asyncio
async def test_openai_streaming_error_chunk_preserves_http_429_status(
    openai_connector: OpenAIConnector,
) -> None:
    """OpenAI streaming error chunks must preserve provider 429 status."""
    streaming_req = ConnectorChatCompletionsRequest(
        request=CanonicalChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            max_tokens=50,
            stream=True,
        ),
        processed_messages=[ChatMessage(role="user", content="Hello")],
        effective_model="gpt-4",
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=ConnectorRequestContext(
            request_id="req-openai-streaming-429",
            session_id="sess-openai-streaming-429",
            client_host="127.0.0.1",
            extensions={},
        ),
        options={},
    )

    async def fake_stream(_request: CanonicalChatRequest):
        for line in _ERROR_STATUS_429_SSE.splitlines(keepends=True):
            if line.strip():
                yield line.encode("utf-8")

    with (
        patch(
            "src.core.di.services.get_or_build_service_provider",
            return_value=_NoopServiceProvider(),
        ),
        patch.object(openai_connector, "stream_completion", fake_stream),
    ):
        result = await openai_connector.chat_completions(streaming_req)

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.status_code == 429

    parsed_chunks = await _collect_chunks(result)
    assert parsed_chunks, "Expected at least one SSE payload chunk"
    assert any(
        chunk.get("choices", [{}])[0].get("finish_reason") == "error"
        for chunk in parsed_chunks
        if isinstance(chunk.get("choices"), list) and chunk.get("choices")
    )

    error_chunks = [
        chunk for chunk in parsed_chunks if isinstance(chunk.get("error"), dict)
    ]
    assert error_chunks, "Expected at least one chunk carrying top-level error payload"
    assert error_chunks[0]["error"].get("status_code") == 429
