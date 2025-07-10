import pytest
from unittest.mock import AsyncMock, patch


def test_banner_injection_gemini_backend(interactive_client):
    """Test that banner injection affects Gemini backend in interactive mode."""
    mock_backend_response = {"choices": [{"message": {"content": "gemini backend response"}}]}
    
    # Set backend to gemini for this test
    original_backend = interactive_client.app.state.backend_type
    interactive_client.app.state.backend_type = "gemini"
    
    try:
        with patch.object(
            interactive_client.app.state.gemini_backend,
            "chat_completions",
            new_callable=AsyncMock,
        ) as mock_method:
            mock_method.return_value = mock_backend_response
            payload = {"model": "gemini-pro", "messages": [{"role": "user", "content": "test"}]}
            resp = interactive_client.post("/v1/chat/completions", json=payload)
        
        assert resp.status_code == 200
        content = resp.json()["choices"][0]["message"]["content"]
        
        print(f"Gemini backend response content: {repr(content)}")
        
        # Check for banner injection
        assert "Hello, this is" in content, "Banner should be injected for Gemini backend"
        assert "Session id" in content, "Session ID should be in banner"
        assert "Functional backends:" in content, "Backend info should be in banner"
        assert "gemini backend response" in content, "Original response should be preserved"
        
        mock_method.assert_called_once()
    finally:
        # Restore original backend
        interactive_client.app.state.backend_type = original_backend


def test_banner_injection_gemini_cli_direct_backend(interactive_client):
    """Test that banner injection affects Gemini CLI Direct backend in interactive mode."""
    mock_backend_response = {"choices": [{"message": {"content": "gemini-cli-direct response"}}]}
    
    # Set backend to gemini-cli-direct for this test
    original_backend = interactive_client.app.state.backend_type
    interactive_client.app.state.backend_type = "gemini-cli-direct"
    
    try:
        with patch.object(
            interactive_client.app.state.gemini_cli_direct_backend,
            "chat_completions",
            new_callable=AsyncMock,
        ) as mock_method:
            mock_method.return_value = mock_backend_response
            payload = {"model": "gemini-2.0-flash-001", "messages": [{"role": "user", "content": "test"}]}
            resp = interactive_client.post("/v1/chat/completions", json=payload)
        
        assert resp.status_code == 200
        content = resp.json()["choices"][0]["message"]["content"]
        
        print(f"Gemini CLI Direct backend response content: {repr(content)}")
        
        # Check for banner injection
        assert "Hello, this is" in content, "Banner should be injected for Gemini CLI Direct backend"
        assert "Session id" in content, "Session ID should be in banner"
        assert "Functional backends:" in content, "Backend info should be in banner"
        assert "gemini-cli-direct response" in content, "Original response should be preserved"
        
        mock_method.assert_called_once()
    finally:
        # Restore original backend
        interactive_client.app.state.backend_type = original_backend


def test_no_banner_injection_with_disabled_interactive(client):
    """Test that banner injection does NOT occur when interactive commands are disabled."""
    mock_backend_response = {"choices": [{"message": {"content": "clean backend response"}}]}
    
    # Debug: Print the actual state values
    print(f"DEBUG: disable_interactive_commands = {client.app.state.disable_interactive_commands}")
    print(f"DEBUG: session manager default_interactive_mode = {client.app.state.session_manager.default_interactive_mode}")
    
    # Get the session to check its interactive mode
    session = client.app.state.session_manager.get_session("default")
    print(f"DEBUG: session proxy_state.interactive_mode = {session.proxy_state.interactive_mode}")
    
    with patch.object(
        client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        mock_method.return_value = mock_backend_response
        payload = {"model": "gpt-4", "messages": [{"role": "user", "content": "test"}]}
        resp = client.post("/v1/chat/completions", json=payload)
    
    assert resp.status_code == 200
    response_data = resp.json()
    
    # Should be exactly the mock response without any banner
    assert response_data == mock_backend_response
    
    content = response_data["choices"][0]["message"]["content"]
    print(f"Non-interactive response content: {repr(content)}")
    
    # Should NOT contain banner elements
    assert "Hello, this is" not in content, "Banner should NOT be injected when interactive disabled"
    assert "Session id" not in content, "Session ID should NOT be in response when interactive disabled"
    assert content == "clean backend response", "Response should be exactly what backend returned"
    
    mock_method.assert_called_once() 