import pytest
from unittest.mock import AsyncMock, patch


def test_cline_output_format_exact(interactive_client):
    """Test that Cline XML output format is exactly as specified - no markdown code blocks."""
    
    # Test the exact output format for Cline
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions", 
        new_callable=AsyncMock,
    ) as mock_method:
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
    
    content = data["choices"][0]["message"]["content"]
    print("=== EXACT OUTPUT FORMAT ===")
    print(repr(content))
    print("=== HUMAN READABLE ===")
    print(content)
    print("=== END OUTPUT ===")
    
    # Verify the format is exactly as specified
    lines = content.split('\n')
    
    # Should start with <attempt_completion>
    assert lines[0] == "<attempt_completion>"
    # Should have <result> on second line
    assert lines[1] == "<result>"
    # Should end with </attempt_completion> (with trailing newline)
    assert lines[-1] == ""  # Trailing newline creates empty last element
    assert lines[-2] == "</attempt_completion>"
    assert lines[-3] == "</result>"
    
    # Should NOT contain markdown code blocks
    assert "```xml" not in content
    assert "```" not in content
    
    # Extract the actual result content (between <result> and </result>)
    result_start = content.find("<result>\n") + len("<result>\n")
    result_end = content.find("\n</result>")
    actual_result = content[result_start:result_end]
    
    print("=== ACTUAL RESULT CONTENT ===")
    print(repr(actual_result))
    print(actual_result)
    
    # The result should contain the hello response
    assert "Hello, this is llm-interactive-proxy" in actual_result
    # Note: "hello acknowledged" is excluded for Cline agents as confirmation messages
    # are only shown to non-Cline clients
    assert "hello acknowledged" not in actual_result
    
    # Verify the complete expected format
    expected_start = "<attempt_completion>\n<result>\n"
    expected_end = "\n</result>\n</attempt_completion>\n"
    
    assert content.startswith(expected_start), f"Content should start with '{expected_start}', got: {content[:50]}"
    assert content.endswith(expected_end), f"Content should end with '{expected_end}', got: {content[-50:]}"


def test_cline_output_format_other_commands(interactive_client):
    """Test XML format for other commands like !/help."""
    
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions", 
        new_callable=AsyncMock,
    ) as mock_method:
        payload = {
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "<attempt_completion>test</attempt_completion> !/help"}
            ]
        }
        resp = interactive_client.post("/v1/chat/completions", json=payload)
        
        mock_method.assert_not_called()
    
    assert resp.status_code == 200
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    
    print("=== HELP COMMAND OUTPUT ===")
    print(content)
    print("=== END HELP OUTPUT ===")
    
    # Should be wrapped in XML
    assert content.startswith("<attempt_completion>\n<result>\n")
    assert content.endswith("\n</result>\n</attempt_completion>\n")
    
    # Should NOT contain markdown code blocks
    assert "```xml" not in content
    assert "```" not in content
    
    # Extract result content
    result_start = content.find("<result>\n") + len("<result>\n")
    result_end = content.find("\n</result>")
    actual_result = content[result_start:result_end]
    
    # Should contain help information
    assert "available commands:" in actual_result or "Available commands:" in actual_result or "Commands:" in actual_result 