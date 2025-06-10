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
    assert "unknown command" in data["choices"][0]["message"]["content"].lower()


@pytest.mark.httpx_mock()
def test_set_command_confirmation(interactive_client, httpx_mock: HTTPXMock):
    interactive_client.app.state.openrouter_backend.available_models = ["foo"]
    # Mock the OpenRouter response
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/chat/completions",
        method="POST",
        json={"choices": [{"message": {"content": "ok"}}]},
        status_code=200,
    )
    payload = {
        "model": "m",
        "messages": [{"role": "user", "content": "hello !/set(model=openrouter:foo)"}],
    }
    resp = interactive_client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 200
    content = resp.json()["choices"][0]["message"]["content"]
    assert "model set to openrouter:foo" in content
    assert "ok" in content


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
    gem_mock.assert_called_once()
    open_mock.assert_not_called()
    content = resp.json()["choices"][0]["message"]["content"]
    assert "backend set to gemini" in content
    assert "resp" in content


@pytest.mark.httpx_mock()
def test_set_backend_nonfunctional(interactive_client, httpx_mock: HTTPXMock):
    interactive_client.app.state.functional_backends = {"openrouter"}
    # Mock the OpenRouter response
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/chat/completions",
        method="POST",
        json={"choices": [{"message": {"content": "ok"}}]},
        status_code=200,
    )
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
    call_kwargs = mock_method.call_args.kwargs
    assert call_kwargs["prompt_redactor"] is None
    assert call_kwargs["processed_messages"][0].content == "leak SECRET"
    content = resp.json()["choices"][0]["message"]["content"]
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
    call_kwargs = mock_method.call_args.kwargs
    assert call_kwargs["prompt_redactor"] is not None
    content = resp.json()["choices"][0]["message"]["content"]
    assert "redact-api-keys-in-prompts unset" in content
