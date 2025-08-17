from unittest.mock import AsyncMock, patch

from src.core.interfaces.backend_service import IBackendService


def test_help_list_commands(test_client):
    """Test help command lists all available commands using new architecture."""
    # Get the backend service from the DI container
    backend_service = test_client.app.state.service_provider.get_required_service(
        IBackendService
    )

    with patch.object(
        backend_service,
        "call_completion",
        new_callable=AsyncMock,
    ) as mock_method:
        payload = {"model": "m", "messages": [{"role": "user", "content": "!/help"}]}
        resp = test_client.post("/v1/chat/completions", json=payload)
        mock_method.assert_not_called()
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "proxy_cmd_processed"
    content = data["choices"][0]["message"]["content"]
    # Check that key commands are present (the registry might have more commands than expected)
    assert "help" in content
    assert "set" in content
    assert "hello" in content
    assert "Available commands:" in content


def test_help_specific_command(test_client):
    """Test help command for specific command using new architecture."""
    # Get the backend service from the DI container
    backend_service = test_client.app.state.service_provider.get_required_service(
        IBackendService
    )
    from src.core.services.command_service import CommandRegistry

    command_registry = test_client.app.state.service_provider.get_required_service(
        CommandRegistry
    )

    with patch.object(
        backend_service,
        "call_completion",
        new_callable=AsyncMock,
    ) as mock_method:
        payload = {
            "model": "m",
            "messages": [{"role": "user", "content": "!/help(set)"}],
        }
        resp = test_client.post("/v1/chat/completions", json=payload)
        mock_method.assert_not_called()
    assert resp.status_code == 200
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    cmd_handler = command_registry.get("set")
    assert cmd_handler is not None
    assert cmd_handler.description in content
    # Check that at least the first few examples are present (help shows first 3)
    for ex in cmd_handler.examples[:3]:
        assert ex in content
