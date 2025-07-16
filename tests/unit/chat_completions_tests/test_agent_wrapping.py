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
    message = data["choices"][0]["message"]

    assert message.get("content") is None
    assert message.get("tool_calls") is not None
    assert len(message["tool_calls"]) == 1
    assert message["tool_calls"][0]["function"]["name"] == "attempt_completion"

    # Verify the content inside the tool call arguments
    tool_call_args = message["tool_calls"][0]["function"]["arguments"]
    import json
    args_dict = json.loads(tool_call_args)
    result_content = args_dict.get("result", "")

    project_name = client.app.state.project_metadata["name"]
    project_version = client.app.state.project_metadata["version"]
    backends_str_expected = "gemini (K:2, M:2), gemini-cli-batch (M:2), gemini-cli-direct (M:2), openrouter (K:2, M:2)"

    expected_lines = [
        f"Hello, this is {project_name} {project_version}",
        "Session id: default", # Default session ID
        f"Functional backends: {backends_str_expected}",
        f"Type {client.app.state.command_prefix}help for list of available commands"
        # Note: "hello acknowledged" is excluded for Cline agents as confirmation messages
        # are only shown to non-Cline clients
    ]
    expected_result_content = "\n".join(expected_lines)
    assert result_content == expected_result_content
