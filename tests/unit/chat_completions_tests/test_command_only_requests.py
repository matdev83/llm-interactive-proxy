import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_command_only_request_direct_response(client):
    client.app.state.openrouter_backend.available_models = ["command-only-model"]
    payload = {
        "model": "some-model",
        "messages": [
            {"role": "user", "content": "!/set(model=openrouter:command-only-model)"}
        ],
    }
    response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["id"] == "proxy_cmd_processed"
    assert (
        "model set to openrouter:command-only-model"
        in response_json["choices"][0]["message"]["content"]
    )
    assert response_json["model"] == payload["model"]

    # The backend's chat_completions method should not be called in this scenario
    # No mock needed here as we are testing the direct proxy response
    from src.core.interfaces.session_service import ISessionService

    session_service = client.app.state.service_provider.get_required_service(
        ISessionService
    )
    session = await session_service.get_session("default")
    assert session.proxy_state.override_model == "command-only-model"


@patch("src.connectors.OpenRouterBackend.chat_completions", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_command_plus_text_direct_response(mock_openrouter_completions, client):
    # Ensure the target model for !/set is available
    target_model_name = (
        "another-model"  # From conftest mock_model_discovery, it's "model-a"
    )
    # Let's use one of the globally mocked ones like "m1" or "model-a"
    target_full_model_id = f"openrouter:{target_model_name}"

    # It's good practice to ensure the models used by commands are "available"
    # The conftest sets up "m1", "m2", "model-a" for openrouter.
    # Let's use "m1" to be specific.
    target_model_name = "m1"
    target_full_model_id = f"openrouter:{target_model_name}"
    # No need to add to client.app.state.openrouter_backend.available_models
    # if conftest's mock_model_discovery fixture correctly populates it.
    # Let's verify it's there or add if necessary for robustness.
    if not client.app.state.openrouter_backend.available_models:
        client.app.state.openrouter_backend.available_models = []
    if target_model_name not in client.app.state.openrouter_backend.available_models:
        client.app.state.openrouter_backend.available_models.append(target_model_name)

    payload = {
        "model": "some-model",  # This is the initial model, will be overridden
        "messages": [
            {
                "role": "user",
                "content": f"This is some user text !/set(model={target_full_model_id}) and more text",
            }
        ],
    }
    response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["id"] == "proxy_cmd_processed"

    # Check for the set command's confirmation message
    expected_confirmation = f"model set to {target_full_model_id}"
    assert expected_confirmation in response_json["choices"][0]["message"]["content"]

    # Ensure the backend was not called
    mock_openrouter_completions.assert_not_called()

    # Verify ProxyState
    from src.core.interfaces.session_service import ISessionService

    session_service = client.app.state.service_provider.get_required_service(
        ISessionService
    )
    session = await session_service.get_session("default")
    assert session.proxy_state.override_model == target_model_name
    assert session.proxy_state.override_backend == "openrouter"


@patch("src.connectors.OpenRouterBackend.chat_completions", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_command_with_agent_prefix_direct_response(
    mock_openrouter_completions, client
):
    agent_model_name = "model-a"  # from conftest mock_model_discovery
    agent_full_model_id = f"openrouter:{agent_model_name}"

    if not client.app.state.openrouter_backend.available_models:
        client.app.state.openrouter_backend.available_models = []
    if agent_model_name not in client.app.state.openrouter_backend.available_models:
        client.app.state.openrouter_backend.available_models.append(agent_model_name)

    payload = {
        "model": "some-initial-model",
        "messages": [
            {
                "role": "user",
                "content": f"<agent_prefix>\nSome instructions\n</agent_prefix>\n!/set(model={agent_full_model_id})",
            }
        ],
    }
    response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["id"] == "proxy_cmd_processed"

    expected_confirmation = f"model set to {agent_full_model_id}"
    assert expected_confirmation in response_json["choices"][0]["message"]["content"]

    mock_openrouter_completions.assert_not_called()

    from src.core.interfaces.session_service import ISessionService

    session_service = client.app.state.service_provider.get_required_service(
        ISessionService
    )
    session = await session_service.get_session("default")
    assert session.proxy_state.override_model == agent_model_name
    assert session.proxy_state.override_backend == "openrouter"


# Also, let's make the original test more robust with explicit mocking
@patch("src.connectors.OpenRouterBackend.chat_completions", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_command_only_request_direct_response_explicit_mock(
    mock_openrouter_completions, client
):
    # This test is similar to the original test_command_only_request_direct_response,
    # but with explicit backend mock and assert_not_called.
    model_to_set = "m2"  # from conftest mock_model_discovery
    model_to_set_full_id = f"openrouter:{model_to_set}"

    if not client.app.state.openrouter_backend.available_models:
        client.app.state.openrouter_backend.available_models = []
    if model_to_set not in client.app.state.openrouter_backend.available_models:
        client.app.state.openrouter_backend.available_models.append(model_to_set)

    payload = {
        "model": "some-model",
        "messages": [
            {"role": "user", "content": f"!/set(model={model_to_set_full_id})"}
        ],
    }
    response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["id"] == "proxy_cmd_processed"

    expected_confirmation = f"model set to {model_to_set_full_id}"
    assert expected_confirmation in response_json["choices"][0]["message"]["content"]
    assert response_json["model"] == payload["model"]  # Check the response model field

    mock_openrouter_completions.assert_not_called()

    from src.core.interfaces.session_service import ISessionService

    session_service = client.app.state.service_provider.get_required_service(
        ISessionService
    )
    session = await session_service.get_session("default")
    assert session.proxy_state.override_model == model_to_set
    assert session.proxy_state.override_backend == "openrouter"


@patch("src.connectors.GeminiBackend.chat_completions", new_callable=AsyncMock)
@patch("src.connectors.OpenRouterBackend.chat_completions", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_hello_command_with_agent_prefix(
    mock_openrouter_completions, mock_gemini_completions, client
):
    """Test !/hello command with an agent prefix."""
    payload = {
        "model": "some-model",
        "messages": [{"role": "user", "content": "Agent Prefix Text\n!/hello"}],
    }
    response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["id"] == "proxy_cmd_processed"
    content = response_json["choices"][0]["message"]["content"]
    assert "Hello, this is" in content
    assert "Functional backends:" in content
    assert "Type !/help" in content

    mock_openrouter_completions.assert_not_called()
    mock_gemini_completions.assert_not_called()


@patch("src.connectors.GeminiBackend.chat_completions", new_callable=AsyncMock)
@patch("src.connectors.OpenRouterBackend.chat_completions", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_hello_command_followed_by_text(
    mock_openrouter_completions, mock_gemini_completions, client
):
    """Test !/hello command followed by other text."""
    payload = {
        "model": "some-model",
        "messages": [{"role": "user", "content": "!/hello\nSome more text from user"}],
    }
    response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["id"] == "proxy_cmd_processed"
    content = response_json["choices"][0]["message"]["content"]
    assert "Hello, this is" in content
    assert "Functional backends:" in content
    assert "Type !/help" in content

    mock_openrouter_completions.assert_not_called()
    mock_gemini_completions.assert_not_called()


@patch("src.connectors.GeminiBackend.chat_completions", new_callable=AsyncMock)
@patch("src.connectors.OpenRouterBackend.chat_completions", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_hello_command_with_prefix_and_suffix(
    mock_openrouter_completions, mock_gemini_completions, client
):
    """Test !/hello command with both prefix and suffix text."""
    payload = {
        "model": "some-model",
        "messages": [
            {"role": "user", "content": "Agent Prefix\n!/hello\nFollow-up text"}
        ],
    }
    response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    response_json = response.json()
    assert response_json["id"] == "proxy_cmd_processed"
    content = response_json["choices"][0]["message"]["content"]
    assert "Hello, this is" in content
    assert "Functional backends:" in content
    assert "Type !/help" in content

    mock_openrouter_completions.assert_not_called()
    mock_gemini_completions.assert_not_called()
