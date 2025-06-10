from unittest.mock import AsyncMock, patch

import pytest
from starlette.responses import StreamingResponse

import src.models as models


def test_session_records_proxy_and_backend_interactions(client):
    with patch.object(
        client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
    ) as mock_method:
        mock_method.return_value = {
            "choices": [{"message": {"content": "backend reply"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        }
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

    session = client.app.state.session_manager.get_session("abc")  # type: ignore
    assert len(session.history) == 2
    assert session.history[0].handler == "proxy"
    assert session.history[0].prompt == "!/set(project=proj1)"
    assert session.history[1].handler == "backend"
    assert session.history[1].backend == "openrouter"
    assert session.history[1].project == "proj1"
    assert session.history[1].response == "backend reply"
    assert session.history[1].usage.total_tokens == 3


def test_session_records_streaming_placeholder(client):
    async def gen():
        yield b"data: hi\n\n"

    stream_resp = StreamingResponse(gen(), media_type="text/event-stream")
    with patch.object(
        client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
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

    session = client.app.state.session_manager.get_session("s2")  # type: ignore
    assert session.history[0].response == "<streaming>"
