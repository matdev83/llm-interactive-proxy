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


# Test Cases based on recent CommandParser changes and requirements

def test_command_embedded_in_xml_tags_processed_locally(interactive_client):
    """
    Test Case 1: Command embedded in XML-like tags.
    Asserts: Backend NOT called, response is local command processing.
    """
    # Ensure the app is in interactive mode (usually default for interactive_client)
    # interactive_client.app.state.session_manager.get_session("default").proxy_state.interactive_mode = True

    with patch.object(
        interactive_client.app.state.openrouter_backend, # Assuming openrouter is default
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_backend_call:
        payload = {
            "model": "any_model", # Model won't be used if command is local
            "messages": [
                {"role": "system", "content": "System Prompt"},
                {"role": "user", "content": "<task>\n!/hello\n</task>"}
            ]
        }
        response = interactive_client.post("/v1/chat/completions", json=payload)

    mock_backend_call.assert_not_called()
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "proxy_cmd_processed"
    # Check for !/hello banner text or confirmation
    assert "Hello, this is" in data["choices"][0]["message"]["content"]
    assert "!/hello" # command itself might not be in output, but its effect is.

def test_command_mixed_with_text_calls_backend_with_modified_text(interactive_client, httpx_mock: HTTPXMock):
    """
    Test Case 2: Command mixed with other text.
    Asserts: Backend IS called, processed_messages is modified, project state updated.
    """
    interactive_client.app.state.openrouter_backend.available_models = ["test-model"]
    # Mock the backend response
    httpx_mock.add_response(
        url=r"https://openrouter.ai/api/v1/chat/completions", # Make it more general if needed
        method="POST",
        json={"choices": [{"message": {"content": "Backend response for mixed text"}}]},
        status_code=200,
    )

    # Patch the actual backend call to inspect arguments
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
        wraps=interactive_client.app.state.openrouter_backend.chat_completions # Wraps to still execute but allow spying
    ) as mock_backend_call:
        payload = {
            "model": "openrouter:test-model", # Specify a model the mock backend knows
            "messages": [{"role": "user", "content": "Some text !/set(project=test-proj) and more text"}]
        }
        response = interactive_client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    mock_backend_call.assert_called_once()

    # Check the arguments passed to the backend
    called_args, called_kwargs = mock_backend_call.call_args
    assert called_kwargs is not None
    processed_messages = called_kwargs.get("processed_messages")
    assert processed_messages is not None
    assert len(processed_messages) == 1
    # The command should be removed, and text normalized (extra spaces).
    # Exact content depends on CommandParser's process_text and _strip_xml_tags behavior.
    # Assuming simple space normalization for this example.
    assert "Some text and more text" == processed_messages[0].content.strip()

    # Check that proxy_state was updated
    session = interactive_client.app.state.session_manager.get_session("default") # Assuming default session_id
    assert session.proxy_state.project == "test-proj"

    # Check that the response includes both command confirmation and backend response
    response_content = response.json()["choices"][0]["message"]["content"]
    assert "project set to test-proj" in response_content # Confirmation from command
    assert "Backend response for mixed text" in response_content # From mocked backend

def test_command_only_message_processed_locally(interactive_client):
    """
    Test Case 3: Command-only message.
    Asserts: Backend NOT called, response is local command processing.
    """
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_backend_call:
        payload = {
            "model": "any_model",
            "messages": [{"role": "user", "content": "!/hello"}]
        }
        response = interactive_client.post("/v1/chat/completions", json=payload)

    mock_backend_call.assert_not_called()
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "proxy_cmd_processed"
    assert "Hello, this is" in data["choices"][0]["message"]["content"]
