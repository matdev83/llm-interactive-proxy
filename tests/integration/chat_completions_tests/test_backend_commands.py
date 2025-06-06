import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

# Removed: from src.main import app (will use configured_app fixture)
from src.session import SessionManager  # Keep SessionManager import

# No local client fixture needed, will use the one from conftest.py


def test_set_backend_command_integration(client: TestClient):
    # Patch app.state.gemini_backend and app.state.openrouter_backend directly on the client's app
    # This ensures the mocks are applied to the specific app instance used by the TestClient
    mock_backend_response = {"choices": [{"message": {"content": "ok"}}]}
    with (
        patch.object(
            client.app.state.gemini_backend, "chat_completions", new_callable=AsyncMock
        ) as gem_mock,
        patch.object(
            client.app.state.openrouter_backend,
            "chat_completions",
            new_callable=AsyncMock,
        ) as open_mock,
    ):
        gem_mock.return_value = mock_backend_response
        payload = {
            "model": "some-model",
            "messages": [{"role": "user", "content": "!/set(backend=gemini) hi"}],
        }
        response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    gem_mock.assert_called_once()
    open_mock.assert_not_called()
    session = client.app.state.session_manager.get_session("default")  # type: ignore
    assert session.proxy_state.override_backend == "gemini"
    content = response.json()["choices"][0]["message"]["content"]
    assert content.endswith("ok") or content.endswith("(no response)")


def test_unset_backend_command_integration(client: TestClient):
    session = client.app.state.session_manager.get_session("default")  # type: ignore
    session.proxy_state.set_override_backend("gemini")
    mock_backend_response = {"choices": [{"message": {"content": "done"}}]}
    with patch.object(
        client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
    ) as open_mock:
        open_mock.return_value = mock_backend_response
        payload = {
            "model": "some-model",
            "messages": [{"role": "user", "content": "!/unset(backend) hi"}],
        }
        response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    open_mock.assert_called_once()
    session = client.app.state.session_manager.get_session("default")  # type: ignore
    assert session.proxy_state.override_backend is None
    assert response.json()["choices"][0]["message"]["content"].endswith("done")


import pytest
from pytest_httpx import HTTPXMock  # Import HTTPXMock


@pytest.mark.httpx_mock()
def test_set_backend_rejects_nonfunctional(client: TestClient, httpx_mock: HTTPXMock):
    # Temporarily modify functional_backends for this test
    original_functional_backends = client.app.state.functional_backends
    client.app.state.functional_backends = {"openrouter"}
    try:
        # Mock the OpenRouter response, as it should still be used
        httpx_mock.add_response(
            url="https://openrouter.ai/api/v1/chat/completions",
            method="POST",
            json={"choices": [{"message": {"content": "ok"}}]},
            status_code=200,
        )

        payload = {
            "model": "some-model",
            "messages": [{"role": "user", "content": "!/set(backend=gemini) hi"}],
        }
        response = client.post("/v1/chat/completions", json=payload)

        assert response.status_code == 200
        session = client.app.state.session_manager.get_session("default")  # type: ignore
        assert (
            session.proxy_state.override_backend is None
        )  # Should not be set to gemini
        content = response.json()["choices"][0]["message"]["content"]
        assert content == "ok" or content.endswith("(no response)")
    finally:
        # Restore functional_backends safely for both ASGI2 and function app types
        app_obj = getattr(client, "app", None)
        state_obj = getattr(app_obj, "state", None)
        if state_obj and hasattr(state_obj, "functional_backends"):
            state_obj.functional_backends = original_functional_backends


def test_set_default_backend_command_integration(client: TestClient):
    mock_backend_response = {"choices": [{"message": {"content": "ok"}}]}
    with (
        patch.object(
            client.app.state.gemini_backend, "chat_completions", new_callable=AsyncMock
        ) as gem_mock,
        patch.object(
            client.app.state.openrouter_backend,
            "chat_completions",
            new_callable=AsyncMock,
        ) as open_mock,
    ):
        gem_mock.return_value = mock_backend_response
        payload = {
            "model": "some-model",
            "messages": [
                {"role": "user", "content": "!/set(default-backend=gemini) hi"}
            ],
        }
        response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    gem_mock.assert_called_once()
    open_mock.assert_not_called()
    assert client.app.state.backend_type == "gemini"
    session = client.app.state.session_manager.get_session("default")  # type: ignore
    assert session.proxy_state.override_backend is None


def test_unset_default_backend_command_integration(client: TestClient):
    client.app.state.backend_type = "gemini"
    client.app.state.backend = client.app.state.gemini_backend
    mock_backend_response = {"choices": [{"message": {"content": "ok"}}]}
    with patch.object(
        client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
    ) as open_mock:
        open_mock.return_value = mock_backend_response
        payload = {
            "model": "some-model",
            "messages": [{"role": "user", "content": "!/unset(default-backend) hi"}],
        }
        response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    open_mock.assert_called_once()
    assert client.app.state.backend_type == client.app.state.initial_backend_type
