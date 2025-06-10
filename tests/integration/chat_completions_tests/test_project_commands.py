from unittest.mock import AsyncMock, patch

import pytest


def test_set_project_command_integration(client):
    mock_backend_response = {"choices": [{"message": {"content": "Project set"}}]}
    with patch.object(
        client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
    ) as mock_method:
        mock_method.return_value = mock_backend_response
        payload = {
            "model": "some-model",
            "messages": [{"role": "user", "content": "!/set(project='proj x') hi"}],
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    session = client.app.state.session_manager.get_session("default")  # type: ignore
    assert session.proxy_state.project == "proj x"
    mock_method.assert_called_once()
    call_args = mock_method.call_args[1]
    assert call_args["project"] == "proj x"
    assert call_args["processed_messages"][0].content == "hi"


def test_unset_project_command_integration(client):
    client.app.state.session_manager.get_session("default").proxy_state.set_project("initial")  # type: ignore
    mock_backend_response = {"choices": [{"message": {"content": "unset"}}]}
    with patch.object(
        client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
    ) as mock_method:
        mock_method.return_value = mock_backend_response
        payload = {
            "model": "some-model",
            "messages": [{"role": "user", "content": "please !/unset(project)"}],
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    session = client.app.state.session_manager.get_session("default")  # type: ignore
    assert session.proxy_state.project is None
    mock_method.assert_called_once()
    call_args = mock_method.call_args[1]
    assert call_args["project"] is None
    assert call_args["processed_messages"][0].content == "please"


def test_set_project_name_alias_integration(client):
    mock_backend_response = {"choices": [{"message": {"content": "ok"}}]}
    with patch.object(
        client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
    ) as mock_method:
        mock_method.return_value = mock_backend_response
        payload = {
            "model": "some-model",
            "messages": [{"role": "user", "content": "!/set(project-name='alias') hi"}],
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    session = client.app.state.session_manager.get_session("default")  # type: ignore
    assert session.proxy_state.project == "alias"
    mock_method.assert_called_once()
    call_args = mock_method.call_args[1]
    assert call_args["project"] == "alias"
    assert call_args["processed_messages"][0].content == "hi"


def test_unset_project_name_alias_integration(client):
    client.app.state.session_manager.get_session("default").proxy_state.set_project("foo")  # type: ignore
    mock_backend_response = {"choices": [{"message": {"content": "ok"}}]}
    with patch.object(
        client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
    ) as mock_method:
        mock_method.return_value = mock_backend_response
        payload = {
            "model": "some-model",
            "messages": [{"role": "user", "content": "!/unset(project-name) hi"}],
        }
        response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    session = client.app.state.session_manager.get_session("default")  # type: ignore
    assert session.proxy_state.project is None
    mock_method.assert_called_once()
    call_args = mock_method.call_args[1]
    assert call_args["project"] is None
    assert call_args["processed_messages"][0].content == "hi"


def test_force_set_project_blocks_requests(client):
    client.app.state.force_set_project = True
    with patch.object(
        client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
    ) as mock_method:
        payload = {"model": "m", "messages": [{"role": "user", "content": "hello"}]}
        resp = client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 400
    assert "project" in resp.json()["detail"].lower()
    mock_method.assert_not_called()


def test_force_set_project_allows_after_set(client):
    client.app.state.force_set_project = True
    mock_response = {"choices": [{"message": {"content": "ok"}}]}
    with patch.object(
        client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
    ) as mock_method:
        mock_method.return_value = mock_response
        payload = {
            "model": "m",
            "messages": [{"role": "user", "content": "!/set(project=foo) hi"}],
        }
        resp = client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 200
    session = client.app.state.session_manager.get_session("default")  # type: ignore
    assert session.proxy_state.project == "foo"
    mock_method.assert_called_once()
