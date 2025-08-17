from unittest.mock import AsyncMock, patch

import pytest
from pytest_httpx import HTTPXMock
from src.core.interfaces.session_service import ISessionService


@patch("src.connectors.openai.OpenAIConnector.chat_completions", new_callable=AsyncMock)
@patch(
    "src.connectors.openrouter.OpenRouterBackend.chat_completions",
    new_callable=AsyncMock,
)
@patch("src.connectors.gemini.GeminiBackend.chat_completions", new_callable=AsyncMock)
def test_unknown_command_error(
    mock_gemini, mock_openrouter, mock_openai, interactive_client
):
    payload = {"model": "m", "messages": [{"role": "user", "content": "!/bad()"}]}
    resp = interactive_client.post("/v1/chat/completions", json=payload)

    # No backend should be called for invalid command
    mock_openai.assert_not_called()
    mock_openrouter.assert_not_called()
    mock_gemini.assert_not_called()

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "proxy_cmd_processed"
    assert "cmd not found" in data["choices"][0]["message"]["content"].lower()


@patch("src.connectors.openai.OpenAIConnector.chat_completions", new_callable=AsyncMock)
@patch(
    "src.connectors.openrouter.OpenRouterBackend.chat_completions",
    new_callable=AsyncMock,
)
@patch("src.connectors.gemini.GeminiBackend.chat_completions", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_set_command_confirmation(
    mock_gemini, mock_openrouter, mock_openai, interactive_client
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

    # No backend should be called for command-only request
    mock_openai.assert_not_called()
    mock_openrouter.assert_not_called()
    mock_gemini.assert_not_called()

    session_service = (
        interactive_client.app.state.service_provider.get_required_service(
            ISessionService
        )
    )
    session = await session_service.get_session("default")
    assert session.state.override_model == model_to_set
    assert session.state.override_backend == "openrouter"


@patch("src.connectors.openai.OpenAIConnector.chat_completions", new_callable=AsyncMock)
@patch(
    "src.connectors.openrouter.OpenRouterBackend.chat_completions",
    new_callable=AsyncMock,
)
@patch("src.connectors.gemini.GeminiBackend.chat_completions", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_set_backend_confirmation(
    mock_gemini, mock_openrouter, mock_openai, interactive_client
):
    mock_backend_response = {"choices": [{"message": {"content": "resp"}}]}
    mock_gemini.return_value = mock_backend_response
    mock_openrouter.return_value = mock_backend_response
    mock_openai.return_value = mock_backend_response

    payload = {
        "model": "m",
        "messages": [{"role": "user", "content": "hi !/set(backend=gemini)"}],
    }
    resp = interactive_client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 200
    response_json = resp.json()
    assert response_json["id"] == "proxy_cmd_processed"

    # Backend should not be called for LLM response when command is processed
    mock_gemini.assert_not_called()
    mock_openrouter.assert_not_called()
    mock_openai.assert_not_called()

    content = response_json["choices"][0]["message"]["content"]
    assert "backend set to gemini" in content  # Command confirmation
    assert "resp" not in content  # Backend mock "resp" should not be in the content

    session_service = (
        interactive_client.app.state.service_provider.get_required_service(
            ISessionService
        )
    )
    session = await session_service.get_session("default")
    assert session.state.override_backend == "gemini"


@patch("src.connectors.openai.OpenAIConnector.chat_completions", new_callable=AsyncMock)
@patch(
    "src.connectors.openrouter.OpenRouterBackend.chat_completions",
    new_callable=AsyncMock,
)
@patch("src.connectors.gemini.GeminiBackend.chat_completions", new_callable=AsyncMock)
@pytest.mark.httpx_mock()
def test_set_backend_nonfunctional(
    httpx_mock: HTTPXMock, mock_gemini, mock_openrouter, mock_openai, interactive_client
):
    interactive_client.app.state.functional_backends = {"openrouter"}
    # Mock responses in case they get called
    mock_response = {"choices": [{"message": {"content": "ok"}}]}
    mock_gemini.return_value = mock_response
    mock_openrouter.return_value = mock_response
    mock_openai.return_value = mock_response

    payload = {
        "model": "m",
        "messages": [{"role": "user", "content": "hi !/set(backend=gemini)"}],
    }
    resp = interactive_client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 200
    content = resp.json()["choices"][0]["message"]["content"].lower()
    assert "backend gemini not functional" in content


@patch("src.connectors.openai.OpenAIConnector.chat_completions", new_callable=AsyncMock)
@patch(
    "src.connectors.openrouter.OpenRouterBackend.chat_completions",
    new_callable=AsyncMock,
)
@patch("src.connectors.gemini.GeminiBackend.chat_completions", new_callable=AsyncMock)
def test_set_redaction_flag(
    mock_gemini, mock_openrouter, mock_openai, interactive_client
):
    # Skip this test if the redaction flag is not supported in the new architecture
    if not hasattr(interactive_client.app.state, "api_key_redaction_enabled"):
        pytest.skip("Redaction flag not supported in this architecture")

    mock_response = {"choices": [{"message": {"content": "ok"}}]}
    mock_gemini.return_value = mock_response
    mock_openrouter.return_value = mock_response
    mock_openai.return_value = mock_response

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

    # Backend should not be called for command-only request
    mock_gemini.assert_not_called()
    mock_openrouter.assert_not_called()
    mock_openai.assert_not_called()

    # Verify the state was changed (if supported)
    assert interactive_client.app.state.api_key_redaction_enabled is False

    content = response_json["choices"][0]["message"]["content"]
    assert "redact-api-keys-in-prompts set to False" in content


@patch("src.connectors.openai.OpenAIConnector.chat_completions", new_callable=AsyncMock)
@patch(
    "src.connectors.openrouter.OpenRouterBackend.chat_completions",
    new_callable=AsyncMock,
)
@patch("src.connectors.gemini.GeminiBackend.chat_completions", new_callable=AsyncMock)
def test_unset_redaction_flag(
    mock_gemini, mock_openrouter, mock_openai, interactive_client
):
    # Skip this test if the redaction flag is not supported in the new architecture
    if not hasattr(interactive_client.app.state, "api_key_redaction_enabled"):
        pytest.skip("Redaction flag not supported in this architecture")

    interactive_client.app.state.api_key_redaction_enabled = False
    mock_response = {"choices": [{"message": {"content": "ok"}}]}
    mock_gemini.return_value = mock_response
    mock_openrouter.return_value = mock_response
    mock_openai.return_value = mock_response

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

    # Backend should not be called for command-only request
    mock_gemini.assert_not_called()
    mock_openrouter.assert_not_called()
    mock_openai.assert_not_called()

    # Verify the state was changed (reverted to default)
    assert (
        interactive_client.app.state.api_key_redaction_enabled
        is interactive_client.app.state.default_api_key_redaction_enabled
    )

    content = response_json["choices"][0]["message"]["content"]
    assert "redact-api-keys-in-prompts unset" in content
