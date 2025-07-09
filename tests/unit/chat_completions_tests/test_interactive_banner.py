from unittest.mock import AsyncMock, patch
import pytest


def test_banner_on_first_reply(interactive_client):
    mock_backend_response = {"choices": [{"message": {"content": "backend"}}]}
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        mock_method.return_value = mock_backend_response
        payload = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
        resp = interactive_client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 200
    content = resp.json()["choices"][0]["message"]["content"]
    # EXPECT PLAIN TEXT NOW
    assert "Hello, this is" in content # From banner
    assert "Session id" in content # From banner
    assert "Functional backends:" in content # From banner
    # Note: The backends_str in _welcome_banner is sorted.
    # openrouter (K:2, M:3), gemini (K:1, M:2). Sorted: gemini, openrouter
    # The banner now includes gemini-cli-direct backend, so check for individual backends
    assert "gemini (K:1, M:2)" in content
    assert "openrouter (K:2, M:3)" in content
    assert "backend" in content # From mock_backend_response
    assert "<attempt_completion>" not in content # Should be plain
    mock_method.assert_called_once()


def test_hello_command_returns_banner(interactive_client):
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        payload = {"model": "m", "messages": [{"role": "user", "content": "!/hello"}]}
        resp = interactive_client.post("/v1/chat/completions", json=payload)
        mock_method.assert_not_called()
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "proxy_cmd_processed"
    content = data["choices"][0]["message"]["content"]
    # EXPECT PLAIN TEXT NOW
    project_name = interactive_client.app.state.project_metadata["name"]
    project_version = interactive_client.app.state.project_metadata["version"]
    # The backends now include gemini-cli-direct, so we need to check the actual content
    backends_str_expected = "gemini (K:1, M:2), gemini-cli-direct (M:4), openrouter (K:2, M:3)" # Sorted

    expected_lines = [
        f"Hello, this is {project_name} {project_version}",
        "Session id: default",
        f"Functional backends: {backends_str_expected}",
        f"Type {interactive_client.app.state.command_prefix}help for list of available commands",
        "hello acknowledged" # Confirmation from HelloCommand
    ]
    expected_content = "\n".join(expected_lines)
    assert content == expected_content
    assert "<attempt_completion>" not in content # Should be plain


def test_hello_command_returns_xml_banner_for_cline_agent(interactive_client):
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        payload = {
            "model": "m",
            "messages": [
                {"role": "user", "content": "This is a message from a cline user."},
                {"role": "user", "content": "!/hello"}
            ]
        }
        resp = interactive_client.post("/v1/chat/completions", json=payload)
        mock_method.assert_not_called()

    assert resp.status_code == 200
    data = resp.json()

    assert data["id"] == "proxy_cmd_processed"
    assert data["object"] == "chat.completion"
    assert data["model"] is not None
    assert len(data["choices"]) == 1
    choice = data["choices"][0]
    assert choice["index"] == 0
    assert choice["finish_reason"] == "stop"

    message = choice["message"]
    assert message["role"] == "assistant"
    content = message["content"]

    assert content.startswith("<attempt_completion>\n<result>\n<thinking>")
    assert content.endswith("\n</thinking>\n</result>\n</attempt_completion>\n")

    start_tag = "<thinking>"
    end_tag = "</thinking>"
    start_index = content.find(start_tag)
    end_index = content.find(end_tag)

    assert start_index != -1, "Start <thinking> tag not found"
    assert end_index != -1, "End </thinking> tag not found"

    thinking_content_with_trailing_newline = content[start_index + len(start_tag):end_index + len(end_tag)]
    assert thinking_content_with_trailing_newline.endswith("\n" + end_tag)
    thinking_content = thinking_content_with_trailing_newline[:-len(end_tag)-1]

    project_name = interactive_client.app.state.project_metadata["name"]
    project_version = interactive_client.app.state.project_metadata["version"]
    backends_str_expected = "gemini (K:1, M:2), gemini-cli-direct (M:4), openrouter (K:2, M:3)"

    expected_lines = [
        f"Hello, this is {project_name} {project_version}",
        "Session id: default",
        f"Functional backends: {backends_str_expected}",
        f"Type {interactive_client.app.state.command_prefix}help for list of available commands",
        "hello acknowledged"
    ]
    expected_thinking_content = "\n".join(expected_lines)

    assert thinking_content == expected_thinking_content
    assert "[Proxy Result]" not in content

    assert "usage" in data
    usage = data["usage"]
    assert usage["prompt_tokens"] == 0
    assert usage["completion_tokens"] == 0
    assert usage["total_tokens"] == 0


def test_set_command_returns_xml_for_cline_agent(interactive_client):
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        payload = {
            "model": "m",
            "messages": [
                {"role": "user", "content": "This is from cline for a set command."},
                {"role": "user", "content": "!/set(backend=openrouter)"} # Changed to use parentheses
            ]
        }
        resp = interactive_client.post("/v1/chat/completions", json=payload)
        mock_method.assert_not_called()

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "proxy_cmd_processed"

    message = data["choices"][0]["message"]
    assert message["role"] == "assistant"
    content = message["content"]

    assert content.startswith("<attempt_completion>\n<result>\n<thinking>")
    assert content.endswith("\n</thinking>\n</result>\n</attempt_completion>\n")

    start_tag = "<thinking>"
    end_tag = "</thinking>"
    start_index = content.find(start_tag)
    end_index = content.find(end_tag)
    assert start_index != -1 and end_index != -1, "Thinking tags not found"

    thinking_content_with_trailing_newline = content[start_index + len(start_tag):end_index + len(end_tag)]
    assert thinking_content_with_trailing_newline.endswith("\n" + end_tag)
    thinking_content = thinking_content_with_trailing_newline[:-len(end_tag)-1]

    assert "backend set to openrouter" in thinking_content
    assert "[Proxy Result]" not in content

    # Check usage field
    assert "usage" in data
    usage = data["usage"]
    assert usage["prompt_tokens"] == 0
    assert usage["completion_tokens"] == 0
    assert usage["total_tokens"] == 0
