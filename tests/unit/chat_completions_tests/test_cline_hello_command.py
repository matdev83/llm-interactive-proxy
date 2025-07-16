from unittest.mock import AsyncMock, patch


def test_cline_hello_command_tool_calls(interactive_client):
    """Test that !/hello command returns tool calls for Cline agent."""
    
    # First, simulate a Cline agent by sending a message with <attempt_completion>
    # This should trigger Cline agent detection
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        mock_method.return_value = {"choices": [{"message": {"content": "I understand"}}]}
        
        # Send a message that contains <attempt_completion> to trigger Cline detection
        payload = {
            "model": "gpt-4", 
            "messages": [
                {"role": "user", "content": "I am a Cline agent. <attempt_completion>test</attempt_completion>"}
            ]
        }
        resp = interactive_client.post("/v1/chat/completions", json=payload)
        assert resp.status_code == 200
    
    # Get the session to check if Cline agent was detected
    session = interactive_client.app.state.session_manager.get_session("default")
    print(f"DEBUG: is_cline_agent after detection = {session.proxy_state.is_cline_agent}")
    print(f"DEBUG: session.agent = {session.agent}")
    
    # Now send the !/hello command - this should return tool calls
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        # The !/hello command should be handled locally, so the backend should not be called
        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "!/hello"}]
        }
        resp = interactive_client.post("/v1/chat/completions", json=payload)
        
        # Backend should NOT be called for local commands
        mock_method.assert_not_called()
    
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "proxy_cmd_processed"
    
    message = data["choices"][0]["message"]
    print(f"Hello command response message: {message}")

    # For Cline agent, should receive tool calls instead of content
    assert message.get("content") is None, "Content should be None for tool calls"
    assert message.get("tool_calls") is not None, "Tool calls should be present"
    assert len(message["tool_calls"]) == 1, "Should have exactly one tool call"
    assert data["choices"][0].get("finish_reason") == "tool_calls", "Finish reason should be tool_calls"

    # Verify tool call structure
    tool_call = message["tool_calls"][0]
    assert tool_call["type"] == "function", "Tool call should be function type"
    assert tool_call["function"]["name"] == "attempt_completion", "Function should be attempt_completion"

    # Verify arguments contain the response
    import json
    args = json.loads(tool_call["function"]["arguments"])
    assert "result" in args, "Arguments should contain result"

    # The result should contain the hello response
    actual_result_content = args["result"]
    assert "Hello, this is" in actual_result_content
    # Note: "hello acknowledged" is excluded for Cline agents as confirmation messages
    # are only shown to non-Cline clients
    assert "hello acknowledged" not in actual_result_content

def test_cline_hello_command_same_request(interactive_client):
    """Test !/hello command when Cline detection and command are in the same request."""
    
    # Send a message that contains BOTH <attempt_completion> AND !/hello in the same request
    # This simulates what might happen in real Cline usage
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        # The !/hello command should be handled locally, so the backend should not be called
        payload = {
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "I am using Cline. <attempt_completion>test</attempt_completion> !/hello"}
            ]
        }
        resp = interactive_client.post("/v1/chat/completions", json=payload)
        
        # Backend should NOT be called for local commands
        mock_method.assert_not_called()
    
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "proxy_cmd_processed"
    
    # Get the session to check if Cline agent was detected
    session = interactive_client.app.state.session_manager.get_session("default")
    print(f"DEBUG: is_cline_agent after same-request detection = {session.proxy_state.is_cline_agent}")
    print(f"DEBUG: session.agent = {session.agent}")
    
    # The response should be a tool call since Cline was detected in the same request
    message = data["choices"][0]["message"]
    assert message.get("content") is None, "Content should be None for tool calls"
    assert message.get("tool_calls") is not None, "Tool calls should be present"
    assert len(message["tool_calls"]) == 1, "Should have exactly one tool call"
    assert data["choices"][0].get("finish_reason") == "tool_calls", "Finish reason should be tool_calls"


def test_cline_hello_with_attempt_completion_only(interactive_client):
    """Test !/hello when only <attempt_completion> is present (real-world Cline scenario)."""
    
    # This simulates the EXACT real-world scenario: Cline sends a message with <attempt_completion>
    # and !/hello, but without the keyword "cline" in the text
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        # The !/hello command should be handled locally, so the backend should not be called
        payload = {
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "<attempt_completion>test</attempt_completion> !/hello"}
            ]
        }
        resp = interactive_client.post("/v1/chat/completions", json=payload)
        
        # Backend should NOT be called for local commands
        mock_method.assert_not_called()
    
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "proxy_cmd_processed"
    
    # Get the session to check if Cline agent was detected
    session = interactive_client.app.state.session_manager.get_session("default")
    print(f"DEBUG: is_cline_agent after attempt_completion-only detection = {session.proxy_state.is_cline_agent}")
    print(f"DEBUG: session.agent = {session.agent}")
    
    # The response should be a tool call since <attempt_completion> was detected
    message = data["choices"][0]["message"]
    assert message.get("content") is None, "Content should be None for tool calls"
    assert message.get("tool_calls") is not None, "Tool calls should be present"
    assert len(message["tool_calls"]) == 1, "Should have exactly one tool call"
    assert data["choices"][0].get("finish_reason") == "tool_calls", "Finish reason should be tool_calls"


def test_cline_hello_command_first_message(interactive_client):
    """Test !/hello as the very first message without prior Cline detection."""
    
    # Send !/hello as the very first message without any prior Cline detection
    # This simulates the real-world scenario you encountered
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "!/hello"}]
        }
        resp = interactive_client.post("/v1/chat/completions", json=payload)
        
        # Backend should NOT be called for local commands
        mock_method.assert_not_called()
    
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "proxy_cmd_processed"
    
    # Get the session to check agent detection status
    session = interactive_client.app.state.session_manager.get_session("default")
    print(f"DEBUG: is_cline_agent for first message = {session.proxy_state.is_cline_agent}")
    print(f"DEBUG: session.agent = {session.agent}")
    
    content = data["choices"][0]["message"]["content"]
    print(f"First message hello command response content: {content!r}")
    
    # Without prior Cline detection, this should NOT be wrapped in XML
    assert not content.startswith("<attempt_completion>"), f"Response should NOT be wrapped in XML without Cline detection, got: {content[:100]}"
    assert "Hello, this is" in content
    assert "hello acknowledged" in content


def test_non_cline_hello_command_no_xml_wrapping(interactive_client):
    """Test that !/hello command is NOT wrapped in XML for non-Cline agents."""
    
    # Send !/hello command without triggering Cline agent detection
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "!/hello"}]
        }
        resp = interactive_client.post("/v1/chat/completions", json=payload)
        
        # Backend should NOT be called for local commands
        mock_method.assert_not_called()
    
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "proxy_cmd_processed"
    
    content = data["choices"][0]["message"]["content"]
    print(f"Non-Cline hello command response content: {content!r}")
    
    # For non-Cline agent, the response should NOT be wrapped in XML
    assert not content.startswith("<attempt_completion>"), f"Response should NOT be wrapped in XML for non-Cline, got: {content[:100]}"
    assert "Hello, this is" in content
    assert "hello acknowledged" in content 