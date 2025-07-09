from unittest.mock import AsyncMock, patch

# import pytest # F401: Removed


def test_cline_command_wrapping(client):
    # Prime session with first message to detect agent
    with patch.object(
        client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
    ) as mock_method:
        mock_method.return_value = {"choices": [{"message": {"content": "ok"}}]}
        payload = {
            "model": "m",
            "messages": [{"role": "system", "content": "You are Cline, use tools"}],
        }
        client.post("/v1/chat/completions", json=payload)

    session = client.app.state.session_manager.get_session("default")
    assert session.agent == "cline"

    payload = {"model": "m", "messages": [{"role": "user", "content": "!/hello"}]}
    resp = client.post("/v1/chat/completions", json=payload)
    data = resp.json()
    assert data["id"] == "proxy_cmd_processed"
    content = data["choices"][0]["message"]["content"]

    assert content.startswith("<attempt_completion>\n<result>\n<thinking>")
    assert content.endswith("\n</thinking>\n</result>\n</attempt_completion>\n")

    # Verify the content inside <thinking> tag
    # This part is similar to test_hello_command_returns_xml_banner_for_cline_agent
    start_tag = "<thinking>"
    end_tag = "</thinking>"
    start_index = content.find(start_tag)
    end_index = content.find(end_tag)
    assert start_index != -1 and end_index != -1, "Thinking tags not found"

    thinking_content_with_trailing_newline = content[start_index + len(start_tag):end_index + len(end_tag)]
    assert thinking_content_with_trailing_newline.endswith("\n" + end_tag)
    thinking_content = thinking_content_with_trailing_newline[:-len(end_tag)-1]

    project_name = client.app.state.project_metadata["name"]
    project_version = client.app.state.project_metadata["version"]
    # Assuming interactive_client's backend setup from conftest.py
    # openrouter (K:2, M:1), gemini (K:1, M:1) - check conftest.py for actual M values
    # The client fixture in test_agent_wrapping.py is 'client', not 'interactive_client'.
    # It uses default_config_data() which has 2 openrouter keys, 1 gemini key.
    # And default mock_openrouter_models (1 model), mock_gemini_models (1 model).
    # So, openrouter (K:2, M:1), gemini (K:1, M:1). Sorted: gemini, openrouter.
    backends_str_expected = "gemini (K:1, M:1), openrouter (K:2, M:1)"

    expected_lines = [
        f"Hello, this is {project_name} {project_version}",
        "Session id: default", # Default session ID
        f"Functional backends: {backends_str_expected}",
        f"Type {client.app.state.command_prefix}help for list of available commands",
        "hello acknowledged" # From !/hello command
    ]
    expected_thinking_content = "\n".join(expected_lines)
    assert thinking_content == expected_thinking_content
