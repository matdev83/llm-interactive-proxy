from unittest.mock import AsyncMock, patch

import pytest
from src.core.domain.responses import ResponseEnvelope
from starlette.responses import StreamingResponse

from tests.conftest import get_backend_instance, get_session_service_from_app


@pytest.mark.skip(reason="Test needs to be rewritten to work with global mock")
@pytest.mark.asyncio
async def test_session_records_proxy_and_backend_interactions(client):
    from src.core.services.backend_service import BackendService

    with patch.object(
        BackendService, "call_completion", new_callable=AsyncMock
    ) as mock_call_completion:
        mock_call_completion.side_effect = [
            ResponseEnvelope(
                content={
                    "id": "cmd-1",
                    "choices": [
                        {"message": {"content": "Command processed successfully"}}
                    ],
                },
                headers={"Content-Type": "application/json"},
                status_code=200,
            ),
            ResponseEnvelope(
                content={
                    "choices": [{"message": {"content": "backend reply"}}],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 2,
                        "total_tokens": 3,
                    },
                },
                headers={"Content-Type": "application/json"},
                status_code=200,
            ),
        ]
        payload1 = {
            "model": "model-a",
            "messages": [{"role": "user", "content": "!/set(project=proj1)"}],
        }
        client.post(
            "/v1/chat/completions", json=payload1, headers={"X-Session-ID": "abc"}
        )

        payload2 = {
            "model": "model-a",
            "messages": [{"role": "user", "content": "hello"}],
        }
        client.post(
            "/v1/chat/completions", json=payload2, headers={"X-Session-ID": "abc"}
        )

    session_service = get_session_service_from_app(client.app)
    session = await session_service.get_session("abc")  # type: ignore
    assert len(session.history) == 2
    assert session.history[0].handler == "proxy_cmd_processed"
    assert session.history[0].prompt == "!/set(project=proj1)"
    assert session.history[1].handler == "backend"
    assert session.history[1].backend == "openrouter"
    assert session.history[1].project == "proj1"
    assert session.history[1].response == "backend reply"
    assert session.history[1].usage.total_tokens == 3


@pytest.mark.skip(reason="Test needs to be rewritten to work with global mock")
@pytest.mark.asyncio
async def test_session_records_streaming_placeholder(client):
    async def gen():
        yield b"data: hi\n\n"

    stream_resp = StreamingResponse(gen(), media_type="text/event-stream")
    backend = get_backend_instance(client.app, "openrouter")
    with patch.object(
        backend, "chat_completions", new_callable=AsyncMock
    ) as mock_method:
        mock_method.return_value = stream_resp
        payload = {
            "model": "model-a",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        }
        client.post(
            "/v1/chat/completions", json=payload, headers={"X-Session-ID": "s2"}
        )

    session_service = get_session_service_from_app(client.app)
    session = await session_service.get_session("s2")  # type: ignore
    assert session.history[0].response == "<streaming>"
