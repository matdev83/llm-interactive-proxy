from unittest.mock import AsyncMock, patch


def test_cline_output_format_exact(interactive_client):
    """Test that Cline XML output format is exactly as specified - no markdown code blocks."""

    # Test the exact output format for Cline
    from tests.conftest import get_backend_instance

    backend = get_backend_instance(interactive_client.app, "openrouter")
    with patch.object(
        backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        payload = {
            "model": "gpt-4",
            "messages": [
                {
                    "role": "user",
                    "content": "<attempt_completion>test</attempt_completion> !/hello",
                }
            ],
        }
        resp = interactive_client.post("/v1/chat/completions", json=payload)

        # Backend should NOT be called for local commands
        mock_method.assert_not_called()

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "proxy_cmd_processed"

    # For Cline agent, the response should be a tool call
    message = data["choices"][0]["message"]
    assert message.get("content") is None, "Content should be None for tool calls"
    assert message.get("tool_calls") is not None, "Tool calls should be present"
    assert len(message["tool_calls"]) == 1, "Should have exactly one tool call"

    tool_call = message["tool_calls"][0]
    assert tool_call["type"] == "function"
    assert tool_call["function"]["name"] == "attempt_completion"

    # The arguments should be a JSON string containing the result
    import json

    try:
        args_dict = json.loads(tool_call["function"]["arguments"])
    except json.JSONDecodeError:
        raise AssertionError(
            f"Failed to decode JSON arguments: {tool_call['function']['arguments']}"
        )

    assert "result" in args_dict, "'result' key missing in tool call arguments"
    actual_result = args_dict["result"]

    print("=== ACTUAL RESULT CONTENT ===")
    print(repr(actual_result))
    print(actual_result)

    # The result should contain the hello response
    assert "Hello, this is llm-interactive-proxy" in actual_result
    # Note: "hello acknowledged" is excluded for Cline agents as confirmation messages
    # are only shown to non-Cline clients
    assert "hello acknowledged" not in actual_result


def test_cline_output_format_other_commands(interactive_client):
    """Test XML format for other commands like !/help."""

    from tests.conftest import get_backend_instance

    backend = get_backend_instance(interactive_client.app, "openrouter")
    with patch.object(
        backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        payload = {
            "model": "gpt-4",
            "messages": [
                {
                    "role": "user",
                    "content": "<attempt_completion>test</attempt_completion> !/help",
                }
            ],
        }
        resp = interactive_client.post("/v1/chat/completions", json=payload)

        mock_method.assert_not_called()

    assert resp.status_code == 200
    data = resp.json()
    # Should be a tool call
    message = data["choices"][0]["message"]
    assert message.get("content") is None, "Content should be None for tool calls"
    assert message.get("tool_calls") is not None, "Tool calls should be present"
    assert len(message["tool_calls"]) == 1, "Should have exactly one tool call"

    tool_call = message["tool_calls"][0]
    assert tool_call["type"] == "function"
    assert tool_call["function"]["name"] == "attempt_completion"

    # Extract result content from JSON arguments
    import json

    try:
        args_dict = json.loads(tool_call["function"]["arguments"])
    except json.JSONDecodeError:
        raise AssertionError(
            f"Failed to decode JSON arguments: {tool_call['function']['arguments']}"
        )

    assert "result" in args_dict, "'result' key missing in tool call arguments"
    actual_result = args_dict["result"]

    # Should contain help information
    assert "available commands:" in actual_result.lower()
