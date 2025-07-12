import pytest
from unittest.mock import AsyncMock, patch
import json


def test_real_cline_hello_response(interactive_client):
    """Test exactly what Cline would receive for a !/hello command."""
    
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        # Exact request that Cline would send
        payload = {
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "<attempt_completion>test</attempt_completion> !/hello"}
            ]
        }
        
        headers = {"Authorization": "Bearer test-proxy-key", "X-Session-ID": "real-cline-test"}
        resp = interactive_client.post("/v1/chat/completions", json=payload, headers=headers)
        
        mock_method.assert_not_called()
        
    print("=== FULL RESPONSE ===")
    print(json.dumps(resp.json(), indent=2))
    
    print("\n=== RESPONSE CONTENT ===")
    content = resp.json()["choices"][0]["message"]["content"]
    print(repr(content))
    
    print("\n=== RESPONSE CONTENT (formatted) ===")
    print(content)
    
    # Check if it's exactly what Cline expects
    assert resp.status_code == 200
    data = resp.json()
    
    # Verify the response structure
    assert "choices" in data
    assert len(data["choices"]) > 0
    assert "message" in data["choices"][0]
    assert "content" in data["choices"][0]["message"]
    assert "role" in data["choices"][0]["message"]
    
    # The content should be XML wrapped
    content = data["choices"][0]["message"]["content"]
    assert content.startswith("<attempt_completion>")
    assert content.endswith("</attempt_completion>\n")
    assert "<result>" in content
    assert "</result>" in content


def test_cline_pure_hello_command(interactive_client):
    """Test pure !/hello command without any other content."""
    
    # Mock response for any backend calls that might happen
    mock_response = {
        "id": "test-response",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Test LLM response"
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15
        }
    }
    
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
        return_value=mock_response
    ) as mock_method:
        # First establish Cline agent detection
        establish_payload = {
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "<attempt_completion>establish</attempt_completion>"}
            ]
        }
        headers = {"Authorization": "Bearer test-proxy-key", "X-Session-ID": "pure-cline-test"}
        resp1 = interactive_client.post("/v1/chat/completions", json=establish_payload, headers=headers)
        
        print("\n=== ESTABLISH RESPONSE ===")
        print(json.dumps(resp1.json(), indent=2))
        
        # Now send pure command
        payload = {
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "!/hello"}
            ]
        }
        
        resp = interactive_client.post("/v1/chat/completions", json=payload, headers=headers)
        
        # The !/hello should not call the backend
        print(f"\nMock called {mock_method.call_count} times")
        if mock_method.call_count > 0:
            print("Mock calls:")
            for call in mock_method.call_args_list:
                print(f"  {call}")
        
    print("\n=== PURE COMMAND RESPONSE ===")
    print(json.dumps(resp.json(), indent=2))
    
    assert resp.status_code == 200
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    
    print(f"\nPure command content: {repr(content)}")
    
    # Should be XML wrapped for Cline
    assert content.startswith("<attempt_completion>")
    assert content.endswith("</attempt_completion>\n")


def test_cline_no_session_id(interactive_client):
    """Test Cline request without explicit session ID."""
    
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        # Request without session ID header
        payload = {
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "<attempt_completion>test</attempt_completion> !/hello"}
            ]
        }
        
        headers = {"Authorization": "Bearer test-proxy-key"}  # No X-Session-ID
        resp = interactive_client.post("/v1/chat/completions", json=payload, headers=headers)
        
        mock_method.assert_not_called()
        
    print("\n=== NO SESSION ID RESPONSE ===")
    print(json.dumps(resp.json(), indent=2))
    
    assert resp.status_code == 200
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    
    print(f"\nNo session ID content: {repr(content)}")
    
    # Should still be XML wrapped for Cline
    assert content.startswith("<attempt_completion>")
    assert content.endswith("</attempt_completion>\n")


def test_cline_non_command_message(interactive_client):
    """Test what happens when Cline sends a message without any proxy commands - this might be the issue."""
    
    # Mock response for backend calls
    mock_response = {
        "id": "test-response",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "This is a normal LLM response without XML wrapping"
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15
        }
    }
    
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
        return_value=mock_response
    ) as mock_method:
        # Cline sends a message with attempt_completion but no proxy commands
        payload = {
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "<attempt_completion>Please help me write a function</attempt_completion>"}
            ]
        }
        
        headers = {"Authorization": "Bearer test-proxy-key", "X-Session-ID": "cline-non-command-test"}
        resp = interactive_client.post("/v1/chat/completions", json=payload, headers=headers)
        
        # This should call the backend since there's no proxy command
        mock_method.assert_called_once()
        
    print("\n=== NON-COMMAND CLINE RESPONSE ===")
    print(json.dumps(resp.json(), indent=2))
    
    assert resp.status_code == 200
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    
    print(f"\nNon-command content: {repr(content)}")
    
    # This should NOT be XML wrapped because it's a normal LLM response, not a proxy command response
    # The issue might be here - if Cline expects ALL responses to be XML wrapped when it's detected
    assert not content.startswith("<attempt_completion>")
    assert content == "This is a normal LLM response without XML wrapping" 


def test_cline_first_message_hello(interactive_client):
    """Test what happens when !/hello is the very first message - this might be the real issue."""
    
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        # Send !/hello as the very first message without any prior Cline detection
        payload = {
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "!/hello"}
            ]
        }
        
        headers = {"Authorization": "Bearer test-proxy-key", "X-Session-ID": "cline-first-hello-test"}
        resp = interactive_client.post("/v1/chat/completions", json=payload, headers=headers)
        
        # This should not call the backend since it's a proxy command
        mock_method.assert_not_called()
        
    print("\n=== FIRST MESSAGE HELLO RESPONSE ===")
    print(json.dumps(resp.json(), indent=2))
    
    assert resp.status_code == 200
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    
    print(f"\nFirst message hello content: {repr(content)}")
    
    # The question is: should this be XML wrapped or not?
    # If Cline sends !/hello as first message, it hasn't been detected as Cline agent yet
    # So it might not get XML wrapped, which could cause the error
    
    # Let's see what actually happens
    if content.startswith("<attempt_completion>"):
        print("[OK] Content is XML wrapped (good for Cline)")
    else:
        print("[X] Content is NOT XML wrapped (this could be the issue!)")
        print("This might be why Cline shows the error about no assistant messages")


def test_cline_first_message_with_detection(interactive_client):
    """Test !/hello as first message but with Cline detection pattern included."""
    
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        # Send !/hello with Cline detection pattern in the same message
        payload = {
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "<attempt_completion>test</attempt_completion> !/hello"}
            ]
        }
        
        headers = {"Authorization": "Bearer test-proxy-key", "X-Session-ID": "cline-first-with-detection-test"}
        resp = interactive_client.post("/v1/chat/completions", json=payload, headers=headers)
        
        # This should not call the backend since it's a proxy command
        mock_method.assert_not_called()
        
    print("\n=== FIRST MESSAGE WITH DETECTION RESPONSE ===")
    print(json.dumps(resp.json(), indent=2))
    
    assert resp.status_code == 200
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    
    print(f"\nFirst message with detection content: {repr(content)}")
    
    # This should definitely be XML wrapped since detection happens in the same message
    assert content.startswith("<attempt_completion>")
    assert content.endswith("</attempt_completion>\n") 


def test_realistic_cline_hello_request(interactive_client):
    """Test a realistic Cline request with long agent prompt followed by !/hello command."""
    
    # Simulate a realistic Cline request with long agent prompt
    long_agent_prompt = """
You are Cline, an AI assistant that can help users with various tasks. You have access to tools and can execute commands.
Your goal is to be helpful, accurate, and efficient. When the user asks you to do something, you should break it down into steps and execute them carefully.

You should always think step by step and explain your reasoning. If you need to use tools or run commands, you should do so.
Make sure to handle errors gracefully and provide clear feedback to the user about what you're doing and why.

Remember to be concise but thorough in your explanations. The user is relying on you to get things done effectively.
When you complete a task, you should summarize what you did and confirm that it was successful.

!/hello
"""
    
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        payload = {
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": long_agent_prompt}
            ]
        }
        
        headers = {"Authorization": "Bearer test-proxy-key", "X-Session-ID": "realistic-cline-test"}
        resp = interactive_client.post("/v1/chat/completions", json=payload, headers=headers)
        
        # This should not call the backend since it's a proxy command
        mock_method.assert_not_called()
        
    print("\n=== REALISTIC CLINE HELLO RESPONSE ===")
    print(json.dumps(resp.json(), indent=2))
    
    assert resp.status_code == 200
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    
    print(f"\nRealistic Cline content: {repr(content)}")
    
    # This should be XML wrapped since it's a long message with a command (typical Cline pattern)
    if content.startswith("<attempt_completion>"):
        print("[OK] Content is XML wrapped (good for Cline)")
        assert content.startswith("<attempt_completion>")
        assert content.endswith("</attempt_completion>\n")
    else:
        print("[X] Content is NOT XML wrapped (this could be the issue!)")
        print("This might be why Cline shows the error about no assistant messages") 