from unittest.mock import AsyncMock, patch

import pytest
from pytest_httpx import HTTPXMock


def test_unknown_command_error(interactive_client):
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        payload = {"model": "m", "messages": [{"role": "user", "content": "!/bad()"}]}
        resp = interactive_client.post("/v1/chat/completions", json=payload)
        mock_method.assert_not_called()
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "proxy_cmd_processed"
    assert "cmd not found" in data["choices"][0]["message"]["content"].lower()


@patch("src.connectors.OpenRouterBackend.chat_completions", new_callable=AsyncMock)
def test_set_command_confirmation(
    mock_openrouter_completions: AsyncMock, interactive_client
):
    # Ensure model is available for the !/set command
    # conftest mock_model_discovery populates ["m1", "m2", "model-a"]
    # Using a model name that is part of the standard mock setup
    model_to_set = "m1"
    full_model_id_to_set = f"openrouter:{model_to_set}"
    if not interactive_client.app.state.openrouter_backend.available_models:
        interactive_client.app.state.openrouter_backend.available_models = []
    if (
        model_to_set
        not in interactive_client.app.state.openrouter_backend.available_models
    ):
        interactive_client.app.state.openrouter_backend.available_models.append(
            model_to_set
        )

    payload = {
        "model": "initial-model",  # This is the model that would be used if no command overrides
        "messages": [
            {"role": "user", "content": f"hello !/set(model={full_model_id_to_set})"}
        ],
    }
    response = interactive_client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["id"] == "proxy_cmd_processed"

    content = response_json["choices"][0]["message"]["content"]
    # The response includes a welcome banner and then the command confirmation.
    assert f"model set to {full_model_id_to_set}" in content

    mock_openrouter_completions.assert_not_called()

    session = interactive_client.app.state.session_manager.get_session("default")
    assert session.proxy_state.override_model == model_to_set
    assert session.proxy_state.override_backend == "openrouter"


def test_set_backend_confirmation(interactive_client):
    mock_backend_response = {"choices": [{"message": {"content": "resp"}}]}
    with (
        patch.object(
            interactive_client.app.state.gemini_backend,
            "chat_completions",
            new_callable=AsyncMock,
        ) as gem_mock,
        patch.object(
            interactive_client.app.state.openrouter_backend,
            "chat_completions",
            new_callable=AsyncMock,
        ) as open_mock,
    ):
        gem_mock.return_value = mock_backend_response
        payload = {
            "model": "m",
            "messages": [{"role": "user", "content": "hi !/set(backend=gemini)"}],
        }
        resp = interactive_client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 200
    response_json = resp.json()
    assert response_json["id"] == "proxy_cmd_processed"

    # Backend should not be called for LLM response when command is processed
    gem_mock.assert_not_called()
    open_mock.assert_not_called()

    content = response_json["choices"][0]["message"]["content"]
    assert "backend set to gemini" in content  # Command confirmation
    assert "resp" not in content  # Backend mock "resp" should not be in the content

    session = interactive_client.app.state.session_manager.get_session("default")
    assert session.proxy_state.override_backend == "gemini"


@pytest.mark.httpx_mock()
def test_set_backend_nonfunctional(interactive_client, httpx_mock: HTTPXMock):
    interactive_client.app.state.functional_backends = {"openrouter"}
    # No backend call is expected if the command fails due to non-functional backend.
    # httpx_mock.add_response(
    #     url="https://openrouter.ai/api/v1/chat/completions",
    #     method="POST",
    #     json={"choices": [{"message": {"content": "ok"}}]},
    #     status_code=200,
    # )
    payload = {
        "model": "m",
        "messages": [{"role": "user", "content": "hi !/set(backend=gemini)"}],
    }
    resp = interactive_client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 200
    content = resp.json()["choices"][0]["message"]["content"].lower()
    assert "backend gemini not functional" in content


def test_set_redaction_flag(interactive_client):
    mock_response = {"choices": [{"message": {"content": "ok"}}]}
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        mock_method.return_value = mock_response
        payload = {
            "model": "m",
            "messages": [
                {
                    "role": "user",
                    "content": "!/set(redact-api-keys-in-prompts=false) leak SECRET",
                }
            ],
        }
        resp = interactive_client.post("/v1/chat/completions", json=payload)

    assert resp.status_code == 200
    response_json = resp.json()
    assert response_json["id"] == "proxy_cmd_processed"

    mock_method.assert_not_called()  # Backend should not be called

    # Verify the state was changed
    assert interactive_client.app.state.api_key_redaction_enabled is False

    content = response_json["choices"][0]["message"]["content"]
    assert "redact-api-keys-in-prompts set to False" in content


def test_unset_redaction_flag(interactive_client):
    interactive_client.app.state.api_key_redaction_enabled = False
    mock_response = {"choices": [{"message": {"content": "ok"}}]}
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        mock_method.return_value = mock_response
        payload = {
            "model": "m",
            "messages": [
                {
                    "role": "user",
                    "content": "!/unset(redact-api-keys-in-prompts) leak SECRET",
                }
            ],
        }
        resp = interactive_client.post("/v1/chat/completions", json=payload)

    assert resp.status_code == 200
    response_json = resp.json()
    assert response_json["id"] == "proxy_cmd_processed"

    mock_method.assert_not_called()  # Backend should not be called

    # Verify the state was changed (reverted to default)
    assert (
        interactive_client.app.state.api_key_redaction_enabled
        is interactive_client.app.state.default_api_key_redaction_enabled
    )

    content = response_json["choices"][0]["message"]["content"]
    assert "redact-api-keys-in-prompts unset" in content
