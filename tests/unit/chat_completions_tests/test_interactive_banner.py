from unittest.mock import AsyncMock, patch


def test_first_reply_no_automatic_banner(interactive_client):
    """Test that first interactions do NOT get automatic banner injection."""
    mock_backend_response = {"choices": [{"message": {"content": "backend"}}]}
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        mock_method.return_value = mock_backend_response
        payload = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
        resp = interactive_client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 200
    content = resp.json()["choices"][0]["message"]["content"]
    # Should be clean backend response without any banner injection
    assert content == "backend"  # Only the backend response
    assert "Hello, this is" not in content  # No automatic banner
    assert "Session id" not in content  # No automatic banner
    assert "Functional backends:" not in content  # No automatic banner
    assert "<attempt_completion>" not in content  # Should be plain
    mock_method.assert_called_once()


def test_hello_command_returns_banner(interactive_client):
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        payload = {"model": "m", "messages": [{"role": "user", "content": "!/hello"}]}
        resp = interactive_client.post("/v1/chat/completions", json=payload)
        mock_method.assert_not_called()
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "proxy_cmd_processed"
    content = data["choices"][0]["message"]["content"]
    # EXPECT PLAIN TEXT NOW
    project_name = interactive_client.app.state.project_metadata["name"]
    project_version = interactive_client.app.state.project_metadata["version"]
    # Get the actual backends from the app state to make test robust
    backend_info = []
    if hasattr(interactive_client.app.state, 'gemini_backend') and interactive_client.app.state.gemini_backend:
        models_count = len(interactive_client.app.state.gemini_backend.get_available_models())
        keys_count = len([k for k in interactive_client.app.state.gemini_backend.api_keys if k])
        backend_info.append(f"gemini (K:{keys_count}, M:{models_count})")
    
    if hasattr(interactive_client.app.state, 'gemini_cli_batch_backend') and interactive_client.app.state.gemini_cli_batch_backend:
        models_count = len(interactive_client.app.state.gemini_cli_batch_backend.get_available_models())
        backend_info.append(f"gemini-cli-batch (M:{models_count})")
    
    if hasattr(interactive_client.app.state, 'gemini_cli_direct_backend') and interactive_client.app.state.gemini_cli_direct_backend:
        models_count = len(interactive_client.app.state.gemini_cli_direct_backend.get_available_models())
        backend_info.append(f"gemini-cli-direct (M:{models_count})")
    
    if hasattr(interactive_client.app.state, 'openrouter_backend') and interactive_client.app.state.openrouter_backend:
        models_count = len(interactive_client.app.state.openrouter_backend.get_available_models())
        keys_count = len([k for k in interactive_client.app.state.openrouter_backend.api_keys if k])
        backend_info.append(f"openrouter (K:{keys_count}, M:{models_count})")
    
    backends_str_expected = ", ".join(sorted(backend_info))

    expected_lines = [
        f"Hello, this is {project_name} {project_version}",
        "Session id: default",
        f"Functional backends: {backends_str_expected}",
        f"Type {interactive_client.app.state.command_prefix}help for list of available commands",
        "hello acknowledged" # Confirmation from HelloCommand
    ]
    expected_content = "\n".join(expected_lines)
    assert content == expected_content
    assert "<attempt_completion>" not in content # Should be plain


def test_hello_command_returns_xml_banner_for_cline_agent(interactive_client):
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        payload = {
            "model": "m",
            "messages": [
                {"role": "user", "content": "This is a message from a cline user."},
                {"role": "user", "content": "!/hello"}
            ]
        }
        resp = interactive_client.post("/v1/chat/completions", json=payload)
        mock_method.assert_not_called()

    assert resp.status_code == 200
    data = resp.json()

    assert data["id"] == "proxy_cmd_processed"
    assert data["object"] == "chat.completion"
    assert data["model"] is not None
    assert len(data["choices"]) == 1
    choice = data["choices"][0]
    assert choice["index"] == 0
    assert choice["finish_reason"] == "stop"

    message = choice["message"]
    assert message["role"] == "assistant"
    content = message["content"]

    assert content.startswith("<attempt_completion>\n<result>\n")
    assert content.endswith("\n</result>\n</attempt_completion>\n")

    project_name = interactive_client.app.state.project_metadata["name"]
    project_version = interactive_client.app.state.project_metadata["version"]
    # Get the actual backends from the app state to make test robust
    backend_info = []
    if hasattr(interactive_client.app.state, 'gemini_backend') and interactive_client.app.state.gemini_backend:
        models_count = len(interactive_client.app.state.gemini_backend.get_available_models())
        keys_count = len([k for k in interactive_client.app.state.gemini_backend.api_keys if k])
        backend_info.append(f"gemini (K:{keys_count}, M:{models_count})")
    
    if hasattr(interactive_client.app.state, 'gemini_cli_batch_backend') and interactive_client.app.state.gemini_cli_batch_backend:
        models_count = len(interactive_client.app.state.gemini_cli_batch_backend.get_available_models())
        backend_info.append(f"gemini-cli-batch (M:{models_count})")
    
    if hasattr(interactive_client.app.state, 'gemini_cli_direct_backend') and interactive_client.app.state.gemini_cli_direct_backend:
        models_count = len(interactive_client.app.state.gemini_cli_direct_backend.get_available_models())
        backend_info.append(f"gemini-cli-direct (M:{models_count})")
    
    if hasattr(interactive_client.app.state, 'openrouter_backend') and interactive_client.app.state.openrouter_backend:
        models_count = len(interactive_client.app.state.openrouter_backend.get_available_models())
        keys_count = len([k for k in interactive_client.app.state.openrouter_backend.api_keys if k])
        backend_info.append(f"openrouter (K:{keys_count}, M:{models_count})")
    
    backends_str_expected = ", ".join(sorted(backend_info))

    expected_lines = [
        f"Hello, this is {project_name} {project_version}",
        "Session id: default",
        f"Functional backends: {backends_str_expected}",
        f"Type {interactive_client.app.state.command_prefix}help for list of available commands"
        # Note: "hello acknowledged" is excluded for Cline agents as confirmation messages
        # are only shown to non-Cline clients
    ]
    expected_result_content = "\n".join(expected_lines)

    # Extract content between <result> and </result>
    start_tag = "<result>\n"
    end_tag = "\n</result>"
    start_index = content.find(start_tag) + len(start_tag)
    end_index = content.find(end_tag)
    actual_result_content = content[start_index:end_index]

    assert actual_result_content == expected_result_content
    assert "[Proxy Result]" not in content

    assert "usage" in data
    usage = data["usage"]
    assert usage["prompt_tokens"] == 0
    assert usage["completion_tokens"] == 0
    assert usage["total_tokens"] == 0


def test_set_command_returns_xml_for_cline_agent(interactive_client):
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        payload = {
            "model": "m",
            "messages": [
                {"role": "user", "content": "This is from cline for a set command."},
                {"role": "user", "content": "!/set(backend=openrouter)"} # Changed to use parentheses
            ]
        }
        resp = interactive_client.post("/v1/chat/completions", json=payload)
        mock_method.assert_not_called()

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "proxy_cmd_processed"

    message = data["choices"][0]["message"]
    assert message["role"] == "assistant"
    content = message["content"]

    assert content.startswith("<attempt_completion>\n<result>\n")
    assert content.endswith("\n</result>\n</attempt_completion>\n")

    # Extract content between <result> and </result>
    start_tag = "<result>\n"
    end_tag = "\n</result>"
    start_index = content.find(start_tag) + len(start_tag)
    end_index = content.find(end_tag)
    actual_result_content = content[start_index:end_index]

    assert "backend set to openrouter" in actual_result_content
    assert "[Proxy Result]" not in content

    # Check usage field
    assert "usage" in data
    usage = data["usage"]
    assert usage["prompt_tokens"] == 0
    assert usage["completion_tokens"] == 0
    assert usage["total_tokens"] == 0

