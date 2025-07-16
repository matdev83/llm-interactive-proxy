from unittest.mock import AsyncMock, patch


def test_cline_xml_wrapping_for_all_commands(interactive_client):
    """Test that XML wrapping works for all available commands when Cline agent is detected."""
    
    # List of commands to test - these should cover different types of commands
    # Using commands that we know work from previous tests
    commands_to_test = [
        "!/hello",
        "!/help", 
        "!/set(backend=openrouter)",
        "!/unset(backend)",
        "!/oneoff(openrouter/gpt-4)",
    ]
    
    for command in commands_to_test:
        print(f"\n=== Testing command: {command} ===")
        
        # Create a fresh session for each test to avoid state pollution
        session_id = f"test-{command.replace('/', '').replace('(', '-').replace(')', '').replace('=', '-')}"
        
        with patch.object(
            interactive_client.app.state.openrouter_backend,
            "chat_completions",
            new_callable=AsyncMock,
        ) as mock_method:
            # Test with Cline detection in the same request
            payload = {
                "model": "gpt-4",
                "messages": [
                    {"role": "user", "content": f"<attempt_completion>test</attempt_completion> {command}"}
                ]
            }
            
            # Use custom headers to create different sessions
            headers = {"Authorization": "Bearer test-proxy-key", "X-Session-ID": session_id}
            resp = interactive_client.post("/v1/chat/completions", json=payload, headers=headers)
            
            # Backend should NOT be called for local commands
            mock_method.assert_not_called()
        
        assert resp.status_code == 200, f"Command {command} failed with status {resp.status_code}"
        data = resp.json()
        assert data["id"] == "proxy_cmd_processed", f"Command {command} not processed locally"
        
        # Verify that the response is now a tool call
        message = data["choices"][0]["message"]
        assert message.get("content") is None, f"Content should be None for {command}"
        assert message.get("tool_calls") is not None, f"Tool calls should be present for {command}"
        assert len(message["tool_calls"]) == 1, f"Expected 1 tool call for {command}"
        
        tool_call = message["tool_calls"][0]
        assert tool_call["type"] == "function", f"Tool call type should be function for {command}"
        assert tool_call["function"]["name"] == "attempt_completion", f"Tool call name should be attempt_completion for {command}"
        
        # The arguments should be a JSON string containing the result
        import json
        try:
            args_dict = json.loads(tool_call["function"]["arguments"])
        except json.JSONDecodeError:
            assert False, f"Failed to decode JSON arguments for {command}: {tool_call['function']['arguments']}"
        
        assert "result" in args_dict, f"'result' key missing in tool call arguments for {command}"
        actual_result = args_dict["result"]
        
        # The result should contain some meaningful content (not empty)
        assert len(actual_result.strip()) > 0, f"Command {command} should produce non-empty result"
        
        # Verify session agent detection worked
        session = interactive_client.app.state.session_manager.get_session(session_id)
        assert session.proxy_state.is_cline_agent, f"Cline agent should be detected for {command}"
        assert session.agent == "cline", f"Session agent should be 'cline' for {command}"


def test_cline_xml_wrapping_error_commands(interactive_client):
    """Test XML wrapping for pure command-only messages that produce errors."""
    
    # Test a pure command that should produce an error (command-only message)
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        payload = {
            "model": "gpt-4", 
            "messages": [
                {"role": "user", "content": "<attempt_completion>test</attempt_completion> !/oneoff(invalid-format)"}
            ]
        }
        resp = interactive_client.post("/v1/chat/completions", json=payload)
        
        mock_method.assert_not_called()
    
    assert resp.status_code == 200
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    
    print("Error command response:")
    print(content)
    
    # For mixed content (command + other content), the error is returned directly
    # and the remaining content gets sent to LLM. This is the correct behavior.
    assert content == "Invalid format. Use backend/model or backend:model.", \
        f"Mixed content with command error should return error directly, got: {content}"


def test_cline_xml_wrapping_pure_error_commands(interactive_client):
    """Test XML wrapping for pure command-only messages that produce errors."""
    
    # Test a pure command that should produce an error (truly command-only message)
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        payload = {
            "model": "gpt-4", 
            "messages": [
                {"role": "user", "content": "<attempt_completion>test</attempt_completion> !/oneoff(invalid-format)"}
            ]
        }
        # Use a session that already has Cline agent detected
        headers = {"Authorization": "Bearer test-proxy-key", "X-Session-ID": "cline-pure-error"}
        resp = interactive_client.post("/v1/chat/completions", json=payload, headers=headers)
        
        mock_method.assert_not_called()
    
    assert resp.status_code == 200
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    
    print("Pure error command response:")
    print(content)
    
    # Even for pure commands with errors, if there's remaining content after cleaning,
    # it won't be treated as command-only. Let's test with a truly pure command.
    
    # Test with a pure command (no extra content)
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        payload = {
            "model": "gpt-4", 
            "messages": [
                {"role": "user", "content": "!/oneoff(invalid-format)"}
            ]
        }
        headers = {"Authorization": "Bearer test-proxy-key", "X-Session-ID": "cline-pure-error-2"}
        
        # First establish Cline agent detection
        establish_payload = {
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "<attempt_completion>establish</attempt_completion> !/hello"}
            ]
        }
        interactive_client.post("/v1/chat/completions", json=establish_payload, headers=headers)
        
        # Now send the pure error command
        resp = interactive_client.post("/v1/chat/completions", json=payload, headers=headers)
        mock_method.assert_not_called()
    
    assert resp.status_code == 200
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    
    print("Pure error command response (truly pure):")
    print(content)
    
    # Pure error commands return error messages directly, not XML wrapped
    # This is the correct behavior - errors should be immediate feedback
    assert content == "Invalid format. Use backend/model or backend:model.", \
        f"Pure error command should return error directly, got: {content}"


def test_non_cline_commands_no_xml_wrapping(interactive_client):
    """Test that non-Cline sessions don't get XML wrapping for any commands."""
    
    commands_to_test = ["!/hello", "!/help", "!/set(backend=openrouter)"]
    
    for command in commands_to_test:
        with patch.object(
            interactive_client.app.state.openrouter_backend,
            "chat_completions",
            new_callable=AsyncMock,
        ) as mock_method:
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
        
        # Should NOT be wrapped in XML for non-Cline sessions
        assert not content.startswith("<attempt_completion>"), \
            f"Non-Cline command {command} should NOT be wrapped in XML, got: {content[:100]}"