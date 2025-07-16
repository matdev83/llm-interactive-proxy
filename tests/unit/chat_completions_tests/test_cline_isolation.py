from unittest.mock import AsyncMock, patch

from src import models


def test_non_cline_clients_no_xml_wrapping(interactive_client):
    """Test that non-Cline clients never get XML wrapping for any commands."""
    
    commands_to_test = [
        "!/hello",
        "!/help", 
        "!/set(backend=openrouter)",
        "!/unset(backend)",
        "!/oneoff(openrouter/gpt-4)",
    ]
    
    for command in commands_to_test:
        print(f"\n=== Testing non-Cline command: {command} ===")
        
        with patch.object(
            interactive_client.app.state.openrouter_backend,
            "chat_completions",
            new_callable=AsyncMock,
        ) as mock_method:
            # Regular client (no Cline detection patterns)
            payload = {
                "model": "gpt-4",
                "messages": [{"role": "user", "content": command}]
            }
            
            # Use different session for each test
            session_id = f"non-cline-{command.replace('/', '').replace('(', '-').replace(')', '').replace('=', '-')}"
            headers = {"Authorization": "Bearer test-proxy-key", "X-Session-ID": session_id}
            resp = interactive_client.post("/v1/chat/completions", json=payload, headers=headers)
            
            mock_method.assert_not_called()
        
        assert resp.status_code == 200
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        
        print(f"Non-Cline response for {command}:")
        print(content)
        print("---")
        
        # Should NOT be wrapped in XML for non-Cline sessions
        assert not content.startswith("<attempt_completion>"), \
            f"Non-Cline command {command} should NOT be wrapped in XML, got: {content[:100]}"
        assert not content.endswith("</attempt_completion>\n"), \
            f"Non-Cline command {command} should NOT end with XML wrapper, got: {content[-100:]}"
        
        # Should NOT contain any XML tags
        assert "<result>" not in content, f"Non-Cline response should not contain <result> tags: {content}"
        assert "</result>" not in content, f"Non-Cline response should not contain </result> tags: {content}"
        
        # Verify session agent detection did NOT happen
        session = interactive_client.app.state.session_manager.get_session(session_id)
        assert not session.proxy_state.is_cline_agent, f"Non-Cline session should not detect Cline agent for {command}"
        assert session.agent != "cline", f"Session agent should NOT be 'cline' for non-Cline request: {command}"


def test_remote_llm_responses_never_xml_wrapped(interactive_client):
    """Test that remote LLM responses are never wrapped in XML, even for Cline agents."""
    
    # Mock successful LLM response
    mock_llm_response = models.ChatCompletionResponse(
        id="test-123",
        object="chat.completion",
        created=1234567890,
        model="gpt-4",
        choices=[
            models.ChatCompletionChoice(
                index=0,
                message=models.ChatCompletionChoiceMessage(
                    role="assistant",
                    content="This is a response from the remote LLM model."
                ),
                finish_reason="stop"
            )
        ],
        usage=models.CompletionUsage(
            prompt_tokens=10,
            completion_tokens=15,
            total_tokens=25
        )
    )
    
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
        return_value=mock_llm_response
    ) as mock_method:
        # Cline agent sending a regular prompt (not a command)
        payload = {
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "<attempt_completion>Please help me with Python</attempt_completion> What is a list comprehension?"}
            ]
        }
        
        headers = {"Authorization": "Bearer test-proxy-key", "X-Session-ID": "cline-llm-test"}
        resp = interactive_client.post("/v1/chat/completions", json=payload, headers=headers)
        
        # Backend SHOULD be called for non-command content
        mock_method.assert_called_once()
    
    assert resp.status_code == 200
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    
    print("Cline agent LLM response:")
    print(content)
    
    # Remote LLM response should NEVER be wrapped in XML, even for Cline agents
    assert not content.startswith("<attempt_completion>"), \
        f"Remote LLM response should NOT be wrapped in XML, got: {content[:100]}"
    assert not content.endswith("</attempt_completion>\n"), \
        f"Remote LLM response should NOT end with XML wrapper, got: {content[-100:]}"
    
    # Should be the exact LLM response
    assert content == "This is a response from the remote LLM model.", \
        f"Remote LLM response should be unchanged, got: {content}"
    
    # Should NOT contain any XML tags
    assert "<result>" not in content, f"Remote LLM response should not contain <result> tags: {content}"
    assert "</result>" not in content, f"Remote LLM response should not contain </result> tags: {content}"
    
    # Verify Cline agent was detected but response is still not wrapped
    session = interactive_client.app.state.session_manager.get_session("cline-llm-test")
    assert session.proxy_state.is_cline_agent, "Cline agent should be detected"
    assert session.agent == "cline", "Session agent should be 'cline'"


def test_mixed_cline_command_and_llm_prompt(interactive_client):
    """Test that when Cline sends both commands and prompts, only commands get XML wrapped."""
    
    # Mock successful LLM response for the prompt part
    mock_llm_response = models.ChatCompletionResponse(
        id="test-456",
        object="chat.completion", 
        created=1234567890,
        model="gpt-4",
        choices=[
            models.ChatCompletionChoice(
                index=0,
                message=models.ChatCompletionChoiceMessage(
                    role="assistant",
                    content="Here's how to use Python lists effectively."
                ),
                finish_reason="stop"
            )
        ],
        usage=models.CompletionUsage(
            prompt_tokens=20,
            completion_tokens=10,
            total_tokens=30
        )
    )
    
    # First, send a command-only request (should get XML wrapped)
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        payload = {
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "<attempt_completion>setup</attempt_completion> !/set(backend=openrouter)"}
            ]
        }
        
        headers = {"Authorization": "Bearer test-proxy-key", "X-Session-ID": "cline-mixed-test"}
        resp = interactive_client.post("/v1/chat/completions", json=payload, headers=headers)
        
        mock_method.assert_not_called()  # Command-only, no LLM call
    
    assert resp.status_code == 200
    data = resp.json()
    command_content = data["choices"][0]["message"]["content"]
    
    print("Command response:")
    print(command_content)
    
    # Command response should be XML wrapped
    assert command_content.startswith("<attempt_completion>\n<result>\n"), \
        "Command response should be XML wrapped"
    
    # Now send a regular prompt (should NOT get XML wrapped)
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
        return_value=mock_llm_response
    ) as mock_method:
        payload = {
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "How do I work with Python lists?"}
            ]
        }
        
        headers = {"Authorization": "Bearer test-proxy-key", "X-Session-ID": "cline-mixed-test"}
        resp = interactive_client.post("/v1/chat/completions", json=payload, headers=headers)
        
        mock_method.assert_called_once()  # Regular prompt, LLM should be called
    
    assert resp.status_code == 200
    data = resp.json()
    llm_content = data["choices"][0]["message"]["content"]
    
    print("LLM response:")
    print(llm_content)
    
    # LLM response should NOT be XML wrapped, even though session is Cline
    assert not llm_content.startswith("<attempt_completion>"), \
        "LLM response should NOT be XML wrapped"
    assert llm_content == "Here's how to use Python lists effectively.", \
        "LLM response should be unchanged"


def test_streaming_responses_never_xml_wrapped(interactive_client):
    """Test that streaming responses from LLMs are never wrapped in XML."""
    
    # Mock streaming response
    async def mock_streaming_response():
        chunks = [
            "This ",
            "is ",
            "a ",
            "streaming ",
            "response."
        ]
        for chunk in chunks:
            yield f"data: {chunk}\n\n"
        yield "data: [DONE]\n\n"
    
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
        return_value=mock_streaming_response()
    ) as mock_method:
        # Cline agent with streaming request
        payload = {
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "<attempt_completion>stream test</attempt_completion> Tell me about Python"}
            ],
            "stream": True
        }
        
        headers = {"Authorization": "Bearer test-proxy-key", "X-Session-ID": "cline-stream-test"}
        resp = interactive_client.post("/v1/chat/completions", json=payload, headers=headers)
        
        mock_method.assert_called_once()
    
    # For streaming, we should get the raw stream back
    assert resp.status_code == 200
    
    # Verify Cline agent was detected
    session = interactive_client.app.state.session_manager.get_session("cline-stream-test")
    assert session.proxy_state.is_cline_agent, "Cline agent should be detected for streaming"
    
    # The streaming response itself should not be modified
    # (We can't easily test the actual stream content in this test setup, 
    # but the key point is that streaming responses bypass XML wrapping entirely)


def test_error_responses_from_llm_never_xml_wrapped(interactive_client):
    """Test that error responses from remote LLMs are never wrapped in XML."""
    
    from fastapi import HTTPException
    
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
        side_effect=HTTPException(status_code=500, detail="LLM backend error")
    ) as mock_method:
        # Cline agent sending a prompt that causes LLM error
        payload = {
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "<attempt_completion>error test</attempt_completion> This will cause an error"}
            ]
        }
        
        headers = {"Authorization": "Bearer test-proxy-key", "X-Session-ID": "cline-error-test"}
        resp = interactive_client.post("/v1/chat/completions", json=payload, headers=headers)
        
        mock_method.assert_called_once()
    
    assert resp.status_code == 500
    
    # Verify Cline agent was detected but error is not wrapped
    session = interactive_client.app.state.session_manager.get_session("cline-error-test")
    assert session.proxy_state.is_cline_agent, "Cline agent should be detected even for errors"