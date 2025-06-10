import logging
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from pytest_httpx import HTTPXMock # E402: Moved to top

from src.proxy_logic import ProxyState

logger = logging.getLogger(__name__)


def test_set_backend_command_integration(client: TestClient):
    client.app.state.functional_backends = {"openrouter", "gemini"}
    mock_backend_response = {"choices": [{"message": {"content": "ok"}}]}

    async def mock_gemini_chat_completions(*args, **kwargs):
        return mock_backend_response

    async def mock_openrouter_chat_completions(*args, **kwargs):
        return mock_backend_response

    mock_proxy_state = MagicMock(spec=ProxyState)
    mock_proxy_state.override_backend = None
    mock_proxy_state.override_model = None
    mock_proxy_state.invalid_override = False
    mock_proxy_state.project = None
    mock_proxy_state.interactive_mode = True
    mock_proxy_state.interactive_just_enabled = False
    mock_proxy_state.hello_requested = False
    mock_proxy_state.failover_routes = {}
    mock_proxy_state.get_effective_model.return_value = "some-model"

    def set_override_backend(backend):
        mock_proxy_state.override_backend = backend
        mock_proxy_state.override_model = None
        mock_proxy_state.invalid_override = False
        logger.info(f"Mock ProxyState: Setting override_backend to {backend}")

    mock_proxy_state.set_override_backend.side_effect = set_override_backend

    def unset_override_backend():
        mock_proxy_state.override_backend = None
        mock_proxy_state.override_model = None
        mock_proxy_state.invalid_override = False
        logger.info("Mock ProxyState: Unsetting override_backend")

    mock_proxy_state.unset_override_backend.side_effect = unset_override_backend

    mock_session = MagicMock()
    mock_session.proxy_state = mock_proxy_state

    with (
        patch.object(
            client.app.state.gemini_backend,
            "chat_completions",
            new=mock_gemini_chat_completions,
        ),
        patch.object(
            client.app.state.openrouter_backend,
            "chat_completions",
            new=mock_openrouter_chat_completions,
        ),
        patch.object(
            client.app.state.gemini_backend,
            "get_available_models",
            return_value=["gemini-model"],
        ),
        patch.object(
            client.app.state.openrouter_backend,
            "get_available_models",
            return_value=["openrouter-model"],
        ),
        patch.object(
            client.app.state.session_manager, "get_session", return_value=mock_session
        ),
    ):
        payload = {
            "model": "some-model",
            "messages": [{"role": "user", "content": "!/set(backend=gemini) hi"}],
        }
        response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    mock_proxy_state.set_override_backend.assert_called_once_with("gemini")
    assert mock_proxy_state.override_backend == "gemini"
    content = response.json()["choices"][0]["message"]["content"]
    assert content.endswith("ok") or content.endswith("(no response)")


def test_unset_backend_command_integration(client: TestClient):
    mock_proxy_state = MagicMock(spec=ProxyState)
    mock_proxy_state.override_backend = "gemini"
    mock_proxy_state.override_model = None
    mock_proxy_state.invalid_override = False
    mock_proxy_state.project = None
    mock_proxy_state.interactive_mode = True
    mock_proxy_state.interactive_just_enabled = False
    mock_proxy_state.hello_requested = False
    mock_proxy_state.failover_routes = {}
    mock_proxy_state.get_effective_model.return_value = "some-model"

    def unset_override_backend():
        mock_proxy_state.override_backend = None
        mock_proxy_state.override_model = None
        mock_proxy_state.invalid_override = False
        logger.info("Mock ProxyState: Unsetting override_backend")

    mock_proxy_state.unset_override_backend.side_effect = unset_override_backend

    mock_session = MagicMock()
    mock_session.proxy_state = mock_proxy_state

    mock_backend_response = {"choices": [{"message": {"content": "done"}}]}

    async def mock_gemini_chat_completions(*args, **kwargs):
        return mock_backend_response

    async def mock_openrouter_chat_completions(*args, **kwargs):
        return mock_backend_response

    with (
        patch.object(
            client.app.state.gemini_backend,
            "chat_completions",
            new=mock_gemini_chat_completions,
        ),
        patch.object(
            client.app.state.openrouter_backend,
            "chat_completions",
            new=mock_openrouter_chat_completions,
        ),
        patch.object(
            client.app.state.gemini_backend,
            "get_available_models",
            return_value=["gemini-model"],
        ),
        patch.object(
            client.app.state.openrouter_backend,
            "get_available_models",
            return_value=["openrouter-model"],
        ),
        patch.object(
            client.app.state.session_manager, "get_session", return_value=mock_session
        ),
    ):
        payload = {
            "model": "some-model",
            "messages": [{"role": "user", "content": "!/unset(backend) hi"}],
        }
        response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    mock_proxy_state.unset_override_backend.assert_called_once()
    assert mock_proxy_state.override_backend is None
    assert response.json()["choices"][0]["message"]["content"].endswith("done")


@pytest.mark.httpx_mock()
def test_set_backend_rejects_nonfunctional(client: TestClient, httpx_mock: HTTPXMock):
    original_functional_backends = client.app.state.functional_backends
    client.app.state.functional_backends = {"openrouter"}
    try:
        # No backend call is expected if the command fails due to non-functional backend.
        # httpx_mock.add_response(
        #     url="https://openrouter.ai/api/v1/chat/completions",
        #     method="POST",
        #     json={"choices": [{"message": {"content": "ok"}}]},
        #     status_code=200,
        # )

        mock_proxy_state = MagicMock(spec=ProxyState)
        mock_proxy_state.override_backend = None
        mock_proxy_state.override_model = None
        mock_proxy_state.invalid_override = False
        mock_proxy_state.project = None
        mock_proxy_state.interactive_mode = True
        mock_proxy_state.interactive_just_enabled = False
        mock_proxy_state.hello_requested = False
        mock_proxy_state.failover_routes = {}
        mock_proxy_state.get_effective_model.return_value = "some-model"

        mock_session = MagicMock()
        mock_session.proxy_state = mock_proxy_state

        with patch.object(
            client.app.state.session_manager, "get_session", return_value=mock_session
        ):
            payload = {
                "model": "some-model",
                "messages": [{"role": "user", "content": "!/set(backend=gemini) hi"}],
            }
            response = client.post("/v1/chat/completions", json=payload)

            assert response.status_code == 200
            assert (
                mock_proxy_state.override_backend is None
            )
            content = response.json()["choices"][0]["message"]["content"]
            assert "backend gemini not functional" in content
    finally:
        app_obj = getattr(client, "app", None)
        state_obj = getattr(app_obj, "state", None)
        if state_obj and hasattr(state_obj, "functional_backends"):
            state_obj.functional_backends = original_functional_backends


def test_set_default_backend_command_integration(client: TestClient):
    mock_proxy_state = MagicMock(spec=ProxyState)
    mock_proxy_state.override_backend = None
    mock_proxy_state.override_model = None
    mock_proxy_state.invalid_override = False
    mock_proxy_state.project = None
    mock_proxy_state.interactive_mode = True
    mock_proxy_state.interactive_just_enabled = False
    mock_proxy_state.hello_requested = False
    mock_proxy_state.failover_routes = {}
    mock_proxy_state.get_effective_model.return_value = "some-model"

    mock_session = MagicMock()
    mock_session.proxy_state = mock_proxy_state

    mock_backend_response = {"choices": [{"message": {"content": "ok"}}]}

    async def mock_gemini_chat_completions(*args, **kwargs):
        return mock_backend_response

    async def mock_openrouter_chat_completions(*args, **kwargs):
        return mock_backend_response

    with (
        patch.object(
            client.app.state.gemini_backend,
            "chat_completions",
            new=mock_gemini_chat_completions,
        ),
        patch.object(
            client.app.state.openrouter_backend,
            "chat_completions",
            new=mock_openrouter_chat_completions,
        ),
        patch.object(
            client.app.state.gemini_backend,
            "get_available_models",
            return_value=["gemini-model"],
        ),
        patch.object(
            client.app.state.openrouter_backend,
            "get_available_models",
            return_value=["openrouter-model"],
        ),
        patch.object(
            client.app.state.session_manager, "get_session", return_value=mock_session
        ),
    ):
        payload = {
            "model": "some-model",
            "messages": [
                {"role": "user", "content": "!/set(default-backend=gemini) hi"}
            ],
        }
        response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    assert client.app.state.backend_type == "gemini"
    assert client.app.state.backend == client.app.state.gemini_backend


def test_unset_default_backend_command_integration(client: TestClient):
    mock_proxy_state = MagicMock(spec=ProxyState)
    mock_proxy_state.override_backend = None
    mock_proxy_state.override_model = None
    mock_proxy_state.invalid_override = False
    mock_proxy_state.project = None
    mock_proxy_state.interactive_mode = True
    mock_proxy_state.interactive_just_enabled = False
    mock_proxy_state.hello_requested = False
    mock_proxy_state.failover_routes = {}
    mock_proxy_state.get_effective_model.return_value = "some-model"

    mock_session = MagicMock()
    mock_session.proxy_state = mock_proxy_state

    client.app.state.backend_type = "gemini"
    client.app.state.backend = client.app.state.gemini_backend
    mock_backend_response = {"choices": [{"message": {"content": "ok"}}]}

    async def mock_gemini_chat_completions(*args, **kwargs):
        return mock_backend_response

    async def mock_openrouter_chat_completions(*args, **kwargs):
        return mock_backend_response

    with (
        patch.object(
            client.app.state.gemini_backend,
            "chat_completions",
            new=mock_gemini_chat_completions,
        ),
        patch.object(
            client.app.state.openrouter_backend,
            "chat_completions",
            new=mock_openrouter_chat_completions,
        ),
        patch.object(
            client.app.state.gemini_backend,
            "get_available_models",
            return_value=["gemini-model"],
        ),
        patch.object(
            client.app.state.openrouter_backend,
            "get_available_models",
            return_value=["openrouter-model"],
        ),
        patch.object(
            client.app.state.session_manager, "get_session", return_value=mock_session
        ),
    ):
        payload = {
            "model": "some-model",
            "messages": [{"role": "user", "content": "!/unset(default-backend) hi"}],
        }
        response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 200
    assert (
        client.app.state.backend_type == "openrouter"
    )
    assert client.app.state.backend == client.app.state.openrouter_backend
