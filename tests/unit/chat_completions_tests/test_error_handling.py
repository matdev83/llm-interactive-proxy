from unittest.mock import AsyncMock, patch

# import pytest # F401: Removed
from fastapi import HTTPException  # Used

# from httpx import Response # F401: Removed
# from starlette.responses import StreamingResponse # F401: Removed

# import src.models as models # F401: Removed


def test_empty_messages_after_processing_no_commands_bad_request(client):
    with patch("src.command_parser.CommandParser.process_messages") as mock_process_msg:
        mock_process_msg.return_value = ([], False)

        with patch.object(
            client.app.state.openrouter_backend,
            "chat_completions",
            new_callable=AsyncMock,
        ) as mock_backend_call:
            payload = {
                "model": "some-model",
                "messages": [{"role": "user", "content": "This will be ignored"}],
            }
            response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 400
    assert "No messages provided" in response.json()["detail"]
    mock_backend_call.assert_not_called()


def test_get_openrouter_headers_no_api_key(client):
    with patch.object(
        client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
    ) as mock_method:
        mock_method.side_effect = HTTPException(
            status_code=500, detail="Simulated backend error due to bad headers"
        )

        payload = {
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "Hello"}],
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 500
    response_json = response.json()
    assert (
        "Simulated backend error due to bad headers" in response_json["detail"]["error"]
    )


def test_invalid_model_noninteractive(client):
    client.app.state.openrouter_backend.available_models = []
    payload = {
        "model": "m",
        "messages": [{"role": "user", "content": "!/set(model=openrouter:bad)"}],
    }
    resp = client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 200
    content = resp.json()["choices"][0]["message"]["content"]
    assert "model openrouter:bad not available" in content

    payload2 = {
        "model": "m",
        "messages": [{"role": "user", "content": "Hello"}],
    }
    resp2 = client.post("/v1/chat/completions", json=payload2)
    assert resp2.status_code in [400, 401]
    if resp2.status_code == 400:
        assert resp2.json()["detail"]["model"] == "openrouter:bad"
    else:
        assert "No auth credentials found" in str(resp2.json())
