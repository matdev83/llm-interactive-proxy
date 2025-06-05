import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from httpx import Response
from starlette.responses import StreamingResponse
from fastapi import HTTPException

from src.main import app, get_openrouter_headers
import src.models as models
from src.session import SessionManager

@pytest.fixture
def client():
    with TestClient(app) as c:
        c.app.state.session_manager = SessionManager()  # type: ignore
        yield c

def test_command_only_request_direct_response(client: TestClient):
    payload = {
        "model": "some-model",
        "messages": [{"role": "user", "content": "!/set(model=command-only-model)"}]
    }
    response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["id"] == "proxy_cmd_processed"
    assert "model set to command-only-model" in response_json["choices"][0]["message"]["content"]
    assert response_json["model"] == "command-only-model"

    # The backend's chat_completions method should not be called in this scenario
    # No mock needed here as we are testing the direct proxy response
    session = client.app.state.session_manager.get_session("default")  # type: ignore
    assert session.proxy_state.override_model == "command-only-model"
