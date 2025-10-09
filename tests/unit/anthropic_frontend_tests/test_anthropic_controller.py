"""Unit tests for the Anthropic controller."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import Request, Response

from src.anthropic_models import AnthropicMessage, AnthropicMessagesRequest
from src.core.app.controllers.anthropic_controller import AnthropicController
from src.core.domain.responses import ResponseEnvelope


def test_handle_messages_propagates_user_metadata() -> None:
    """Ensure metadata.user_id is forwarded to the domain ChatRequest."""

    envelope_content = {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "model": "gpt-4o-mini",
        "choices": [
            {
                "message": {"role": "assistant", "content": "Hello"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2},
    }

    processor = MagicMock()
    processor.process_request = AsyncMock(
        return_value=ResponseEnvelope(
            content=envelope_content,
            headers={},
            status_code=200,
            media_type="application/json",
        )
    )

    controller = AnthropicController(processor)
    request = MagicMock(spec=Request)

    async def invoke() -> Response:
        with patch(
            "src.core.app.controllers.anthropic_controller.fastapi_to_domain_request_context",
            return_value=MagicMock(),
        ):
            return await controller.handle_anthropic_messages(
                request,
                AnthropicMessagesRequest(
                    model="claude-3-sonnet-20240229",
                    messages=[AnthropicMessage(role="user", content="Hello")],
                    metadata={"user_id": "user-123"},
                    max_tokens=64,
                ),
            )

    response = asyncio.run(invoke())

    awaited_call = processor.process_request.await_args
    chat_request = awaited_call.args[1]

    assert chat_request.user == "user-123"
    assert response.status_code == 200
    # Response body should be valid JSON after Anthropic conversion
    assert json.loads(response.body)
