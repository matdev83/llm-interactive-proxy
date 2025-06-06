import pytest
from unittest.mock import AsyncMock, patch

from httpx import Response
from starlette.responses import StreamingResponse
from fastapi import HTTPException

import src.models as models

def test_command_only_request_direct_response(client):
    client.app.state.openrouter_backend.available_models = ["command-only-model"]
    payload = {
        "model": "some-model",
        "messages": [{"role": "user", "content": "!/set(model=openrouter:command-only-model)"}]
    }
    response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["id"] == "proxy_cmd_processed"
    assert "model set to openrouter:command-only-model" in response_json["choices"][0]["message"]["content"]
    assert response_json["model"] == "command-only-model"

    # The backend's chat_completions method should not be called in this scenario
    # No mock needed here as we are testing the direct proxy response
    session = client.app.state.session_manager.get_session("default")  # type: ignore
    assert session.proxy_state.override_model == "command-only-model"
