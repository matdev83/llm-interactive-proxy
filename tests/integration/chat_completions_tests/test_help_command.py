from unittest.mock import AsyncMock, patch

from src.commands import command_registry


def test_help_list_commands(interactive_client):
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        payload = {"model": "m", "messages": [{"role": "user", "content": "!/help"}]}
        resp = interactive_client.post("/v1/chat/completions", json=payload)
        mock_method.assert_not_called()
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "proxy_cmd_processed"
    expected = ", ".join(sorted(command_registry.keys()))
    assert expected in data["choices"][0]["message"]["content"]


def test_help_specific_command(interactive_client):
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        payload = {
            "model": "m",
            "messages": [{"role": "user", "content": "!/help(set)"}],
        }
        resp = interactive_client.post("/v1/chat/completions", json=payload)
        mock_method.assert_not_called()
    assert resp.status_code == 200
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    cmd_cls = command_registry["set"]
    assert cmd_cls.description in content
    for ex in cmd_cls.examples:
        assert ex in content
