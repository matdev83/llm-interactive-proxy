import pytest
from unittest.mock import AsyncMock, patch


def test_cline_hello_command_xml_wrapping(interactive_client):
    """Test that !/hello command is properly wrapped in XML for Cline agent."""
    
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
    
    # Now send the !/hello command - this should be wrapped in XML
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
    
    content = data["choices"][0]["message"]["content"]
    print(f"Hello command response content: {repr(content)}")
    
    # For Cline agent, the response should be wrapped in XML
    assert content.startswith("<attempt_completion>\n<result>\n"), f"Response should start with XML wrapper, got: {content[:100]}"
    assert content.endswith("\n</result>\n</attempt_completion>\n"), f"Response should end with XML wrapper, got: {content[-100:]}"
    
    # Extract content between <result> and </result>
    start_tag = "<result>\n"
    end_tag = "\n</result>"
    start_index = content.find(start_tag) + len(start_tag)
    end_index = content.find(end_tag)
    actual_result_content = content[start_index:end_index]
    
    # The result should contain the hello response
    assert "Hello, this is" in actual_result_content
    assert "hello acknowledged" in actual_result_content


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
    
    content = data["choices"][0]["message"]["content"]
    print(f"Same-request hello command response content: {repr(content)}")
    
    # The response should be wrapped in XML since Cline was detected in the same request
    assert content.startswith("<attempt_completion>\n<result>\n"), f"Response should start with XML wrapper, got: {content[:100]}"
    assert content.endswith("\n</result>\n</attempt_completion>\n"), f"Response should end with XML wrapper, got: {content[-100:]}"


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
    
    content = data["choices"][0]["message"]["content"]
    print(f"Attempt_completion-only hello command response content: {repr(content)}")
    
    # The response should be wrapped in XML since <attempt_completion> was detected
    assert content.startswith("<attempt_completion>\n<result>\n"), f"Response should start with XML wrapper, got: {content[:100]}"
    assert content.endswith("\n</result>\n</attempt_completion>\n"), f"Response should end with XML wrapper, got: {content[-100:]}"


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
    print(f"First message hello command response content: {repr(content)}")
    
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
    print(f"Non-Cline hello command response content: {repr(content)}")
    
    # For non-Cline agent, the response should NOT be wrapped in XML
    assert not content.startswith("<attempt_completion>"), f"Response should NOT be wrapped in XML for non-Cline, got: {content[:100]}"
    assert "Hello, this is" in content
    assert "hello acknowledged" in content 