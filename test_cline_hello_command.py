import pytest
from unittest.mock import AsyncMock, patch
import sys
import os

# Add src to path
sys.path.insert(0, 'src')

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
    assert content.endswith("\n</result>\n<command></command>\n</attempt_completion>\n"), f"Response should end with XML wrapper, got: {content[-100:]}"
    
    # Extract content between <result> and </result>
    start_tag = "<result>\n"
    end_tag = "\n</result>"
    start_index = content.find(start_tag) + len(start_tag)
    end_index = content.find(end_tag)
    actual_result_content = content[start_index:end_index]
    
    # The result should contain the hello response
    assert "Hello, this is" in actual_result_content
    assert "hello acknowledged" in actual_result_content


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


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v", "-s"]) 