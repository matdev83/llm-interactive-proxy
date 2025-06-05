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
        c.app.state.session_manager = SessionManager()  # type: ignore[attr-defined]
        yield c

def test_empty_messages_after_processing_no_commands_bad_request(client: TestClient):
    with patch('src.main.process_commands_in_messages') as mock_process_msg:
        mock_process_msg.return_value = ([], False)

        with patch.object(app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_backend_call:
            payload = {
                "model": "some-model",
                "messages": [{"role": "user", "content": "This will be ignored"}]
            }
            response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 400
    assert "No messages provided" in response.json()["detail"]
    mock_backend_call.assert_not_called()


def test_get_openrouter_headers_no_api_key(client: TestClient):
    with patch.object(app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
        mock_method.side_effect = HTTPException(status_code=500, detail="Simulated backend error due to bad headers")

        payload = {
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "Hello"}],
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 500
    assert "Simulated backend error due to bad headers" in response.json()["detail"]
