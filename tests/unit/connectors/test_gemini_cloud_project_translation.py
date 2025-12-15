from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock

import httpx
import pytest
from src.connectors.gemini_cloud_project import GeminiCloudProjectConnector
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.services.translation_service import TranslationService


def _make_connector() -> GeminiCloudProjectConnector:
    client = Mock(spec=httpx.AsyncClient)
    config = AppConfig()
    return GeminiCloudProjectConnector(
        client,
        config,
        translation_service=TranslationService(),
        gcp_project_id="test-project",
    )


def test_normalize_openai_response_accepts_dict() -> None:
    connector = _make_connector()
    payload = {"object": "chat.completion"}

    result = connector._normalize_openai_response(payload)

    assert result is payload


def test_normalize_openai_response_uses_model_dump() -> None:
    connector = _make_connector()

    class DummyResponse:
        def model_dump(self, exclude_unset: bool = True) -> dict[str, str]:
            return {"object": "chat.completion"}

    result = connector._normalize_openai_response(DummyResponse())

    assert result == {"object": "chat.completion"}


def test_normalize_openai_response_rejects_unknown_type() -> None:
    connector = _make_connector()

    with pytest.raises(BackendError):
        connector._normalize_openai_response(object())


@pytest.mark.asyncio
async def test_streaming_envelope_has_no_cancel_callback() -> None:
    translation_service = MagicMock()
    connector = GeminiCloudProjectConnector(
        client=AsyncMock(),
        config=AppConfig(),
        translation_service=translation_service,
        gcp_project_id="test-project",
    )
    connector.gemini_api_base_url = "https://cloudcode-pa.googleapis.com"

    connector.translation_service.from_domain_to_gemini_request.return_value = {
        "contents": [{"role": "user", "parts": [{"text": "Hi"}]}]
    }
    connector.translation_service.to_domain_stream_chunk.side_effect = (
        lambda chunk, source_format: (
            {"choices": [{"delta": {"content": "Hi"}}]}
            if chunk
            else {"choices": [{"delta": {}, "finish_reason": "stop"}]}
        )
    )

    stream_response = MagicMock()
    stream_response.status_code = 200

    def _iter_content(chunk_size: int = 1, decode_unicode: bool = False):
        data = b'data: {"choices": [{"delta": {"content": "Hi"}}]}\n' b"data: [DONE]\n"
        for byte in data:
            yield bytes([byte])

    stream_response.iter_content.side_effect = _iter_content
    stream_response.close = MagicMock()

    mock_session = MagicMock()
    mock_session.request.return_value = stream_response

    connector._get_adc_authorized_session = MagicMock(return_value=mock_session)
    connector._ensure_project_onboarded = AsyncMock(return_value="user-project")

    request = ChatRequest(
        model="gemini-cli-cloud-project:gemini-pro",
        messages=[ChatMessage(role="user", content="Hi")],
        stream=True,
    )

    envelope = await connector._chat_completions_streaming(
        request_data=request,
        processed_messages=[ChatMessage(role="user", content="Hi")],
        effective_model="gemini-pro",
    )

    assert isinstance(envelope, StreamingResponseEnvelope)
    assert envelope.cancel_callback is None
