import pytest


@pytest.mark.skip(reason="Test needs to be updated for new architecture")
def test_cline_command_wrapping(client):
    # Skip this test for now as it requires legacy backend setup
    # TODO: Update this test to work with the new architecture
    import pytest

    pytest.skip("Test needs to be updated for new architecture")

    payload = {"model": "m", "messages": [{"role": "user", "content": "!/hello"}]}
    headers = {"Authorization": "Bearer test_api_key"}
    resp = client.post("/v1/chat/completions", json=payload, headers=headers)
    data = resp.json()
    assert data["id"] == "proxy_cmd_processed"
    message = data["choices"][0]["message"]

    assert message.get("content") is None
    assert message.get("tool_calls") is not None
    assert len(message["tool_calls"]) == 1
    assert message["tool_calls"][0]["function"]["name"] == "attempt_completion"

    # Verify the content inside the tool call arguments
    tool_call_args = message["tool_calls"][0]["function"]["arguments"]
    import json

    args_dict = json.loads(tool_call_args)
    result_content = args_dict.get("result", "")

    from tests.conftest import get_backend_instance

    project_name = client.app.state.project_metadata["name"]
    project_version = client.app.state.project_metadata["version"]
    # Get the actual backends from DI helpers to make test robust
    backend_info = []
    gemini = get_backend_instance(client.app, "gemini")
    if gemini:
        models_count = len(gemini.get_available_models())
        keys_count = len([k for k in getattr(gemini, "api_keys", []) if k])
        backend_info.append(f"gemini (K:{keys_count}, M:{models_count})")

    openrouter = get_backend_instance(client.app, "openrouter")
    if openrouter:
        models_count = len(openrouter.get_available_models())
        keys_count = len([k for k in getattr(openrouter, "api_keys", []) if k])
        backend_info.append(f"openrouter (K:{keys_count}, M:{models_count})")

    # We've disabled Qwen OAuth backend for these tests

    backends_str_expected = ", ".join(sorted(backend_info))

    expected_lines = [
        f"Hello, this is {project_name} {project_version}",
        "Session id: default",  # Default session ID
        f"Functional backends: {backends_str_expected}",
        f"Type {client.app.state.command_prefix}help for list of available commands",
        # Note: "hello acknowledged" is excluded for Cline agents as confirmation messages
        # are only shown to non-Cline clients
    ]
    expected_result_content = "\n".join(expected_lines)
    assert result_content == expected_result_content
