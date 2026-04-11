from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from src.core.app.controllers.chat_controller import ChatController
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.usage_summary import UsageSummary


@pytest.mark.asyncio
async def test_chat_controller_preserves_envelope_usage_for_string_content() -> None:
    processor = AsyncMock()
    processor.process_request = AsyncMock(
        return_value=ResponseEnvelope(
            content="plain assistant text",
            usage=UsageSummary.from_dict(
                {"input_tokens": 21, "output_tokens": 8, "total_tokens": 29}
            ),
            metadata={"model": "openai-codex:gpt-5-codex"},
        )
    )

    controller = ChatController(
        request_processor=processor,
        translation_service=None,
        wire_capture=None,
        metrics_initializer=None,
    )

    request = Mock()
    request.body = AsyncMock(return_value=b"{}")
    request.method = "POST"
    request.url = SimpleNamespace(path="/v1/chat/completions")
    request.headers = {}
    request.cookies = {}
    request.state = SimpleNamespace()
    request.app = SimpleNamespace(state=SimpleNamespace(service_provider=None))

    request_data = ChatRequest(
        model="openai-codex:gpt-5-codex",
        messages=[ChatMessage(role="user", content="hello")],
        stream=False,
    )

    response = await controller.handle_chat_completion(request, request_data)

    body = (
        response.body.tobytes()
        if isinstance(response.body, memoryview)
        else response.body
    )
    payload = json.loads(body.decode("utf-8"))

    assert payload["usage"]["prompt_tokens"] == 21
    assert payload["usage"]["completion_tokens"] == 8
    assert payload["usage"]["total_tokens"] == 29
