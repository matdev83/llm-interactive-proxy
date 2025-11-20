"""
Unit tests for the Cline backend connector.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, call, patch

import pytest
from fastapi import HTTPException
from src.connectors.cline import ClineConnector
from src.connectors.openai import OpenAIConnector
from src.core.common.exceptions import AuthenticationError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.services.translation_service import TranslationService


class _DummyResponse:
    def __init__(self, status_code: int = 200, data: dict | None = None) -> None:
        self.status_code = status_code
        self._data = data or {"data": []}
        self.text = json.dumps(self._data)

    def json(self) -> dict:
        return self._data


def _write_auth_payload(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    contents = {"cline:clineAccountId": json.dumps(payload)}
    path.write_text(json.dumps(contents), encoding="utf-8")


def _make_jwt(expiry: float, sub: str = "user-123") -> str:
    header = (
        base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        .decode("utf-8")
        .rstrip("=")
    )
    payload = (
        base64.urlsafe_b64encode(json.dumps({"exp": expiry, "sub": sub}).encode())
        .decode("utf-8")
        .rstrip("=")
    )
    return f"{header}.{payload}.signature"


@pytest.fixture
def http_client():
    client = AsyncMock()
    client.get = AsyncMock(return_value=_DummyResponse())
    client.post = AsyncMock(return_value=_DummyResponse())
    return client


@pytest.fixture
def config():
    return AppConfig()


@pytest.fixture
def translation_service():
    return TranslationService()


@pytest.mark.asyncio
async def test_initialize_loads_token_from_secrets(
    http_client, config, translation_service, tmp_path
):
    """Connector should read the stored token and configure the API key."""
    secrets_path = tmp_path / "secrets.json"
    payload = {
        "idToken": "abc123",
        "refreshToken": "refresh-token",
        "expiresAt": time.time() + 3600,
        "userInfo": {"id": "user"},
        "provider": "cline",
    }
    _write_auth_payload(secrets_path, payload)

    connector = ClineConnector(http_client, config, translation_service)
    await connector.initialize(secrets_path=secrets_path)

    assert connector.api_key == "workos:abc123"
    http_client.get.assert_awaited()  # Models listing during initialize


@pytest.mark.asyncio
async def test_initialize_raises_when_token_missing(
    http_client, config, translation_service, tmp_path
):
    """Missing auth data should raise an AuthenticationError."""
    secrets_path = tmp_path / "secrets.json"
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    secrets_path.write_text("{}", encoding="utf-8")

    connector = ClineConnector(http_client, config, translation_service)
    with (
        patch.object(
            ClineConnector,
            "_load_tokens_from_vscode_secret_store",
            return_value=None,
        ),
        patch.object(ClineConnector, "_load_tokens_from_codex_auth", return_value=None),
        pytest.raises(AuthenticationError),
    ):
        await connector.initialize(secrets_path=secrets_path)


@pytest.mark.asyncio
async def test_initialize_refreshes_expired_token(
    http_client, config, translation_service, tmp_path
):
    """Expired tokens should trigger the refresh flow during initialization."""
    secrets_path = tmp_path / "secrets.json"
    stored_payload = {
        "idToken": "expired-token",
        "refreshToken": "refresh-me",
        "expiresAt": time.time() - 5,
        "userInfo": {"id": "user"},
        "provider": "cline",
    }
    refreshed_payload = {
        "idToken": "new-token",
        "refreshToken": "refresh-me",
        "expiresAt": time.time() + 600,
        "userInfo": {"id": "user"},
        "provider": "cline",
    }
    _write_auth_payload(secrets_path, stored_payload)

    connector = ClineConnector(http_client, config, translation_service)
    with patch.object(
        ClineConnector,
        "_refresh_tokens",
        new=AsyncMock(return_value=refreshed_payload),
    ) as mock_refresh:
        await connector.initialize(secrets_path=secrets_path)

    mock_refresh.assert_awaited_once()
    refresh_args = mock_refresh.await_args
    assert refresh_args.args[0] == "refresh-me"
    assert connector.api_key == "workos:new-token"


@pytest.mark.asyncio
async def test_initialize_uses_codex_auth_when_secrets_missing(
    http_client, config, translation_service, tmp_path
):
    """Codex CLI auth should be used as a fallback when Cline secrets are missing."""
    auth_path = tmp_path / "codex" / "auth.json"
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    expiry = time.time() + 900
    codex_auth = {
        "tokens": {
            "access_token": _make_jwt(expiry, sub="acct-user"),
            "refresh_token": "refresh-token",
            "account_id": "acct-user",
        }
    }
    auth_path.write_text(json.dumps(codex_auth), encoding="utf-8")
    secrets_path = tmp_path / "cline" / "secrets.json"
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    secrets_path.write_text("{}", encoding="utf-8")

    refreshed_payload = {
        "idToken": "converted-token",
        "refreshToken": "converted-refresh",
        "expiresAt": expiry + 120,
        "userInfo": {"id": "cline-user"},
        "provider": "cline",
    }

    connector = ClineConnector(http_client, config, translation_service)
    with (
        patch.object(
            ClineConnector,
            "_load_tokens_from_vscode_secret_store",
            return_value=None,
        ),
        patch.object(
            ClineConnector,
            "_refresh_tokens",
            new=AsyncMock(return_value=refreshed_payload),
        ),
    ):
        await connector.initialize(secrets_path=secrets_path, codex_auth_path=auth_path)

    assert connector.api_key == "workos:converted-token"
    stored_data = json.loads(secrets_path.read_text())
    serialized = stored_data["cline:clineAccountId"]
    cline_payload = json.loads(serialized)
    assert cline_payload == refreshed_payload


@pytest.mark.asyncio
async def test_initialize_uses_vscode_secrets_when_available(
    http_client, config, translation_service, tmp_path
):
    """VSCode secret store should supply credentials if disk secrets are empty."""
    secrets_path = tmp_path / "cline" / "secrets.json"
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    secrets_path.write_text("{}", encoding="utf-8")

    vscode_payload = {
        "idToken": "vscode-token",
        "refreshToken": "refresh-vscode",
        "expiresAt": time.time() + 300,
        "userInfo": {"id": "vscode-user"},
        "provider": "cline",
    }

    connector = ClineConnector(http_client, config, translation_service)
    with patch.object(
        ClineConnector,
        "_load_tokens_from_vscode_secret_store",
        return_value=vscode_payload,
    ):
        await connector.initialize(secrets_path=secrets_path)

    assert connector.api_key == "workos:vscode-token"


@pytest.mark.asyncio
async def test_chat_completions_reloads_updated_token(
    http_client, config, translation_service, tmp_path
):
    """When the secrets file changes, the connector should reload the token before the next call."""
    secrets_path = tmp_path / "secrets.json"
    initial_payload = {
        "idToken": "first-token",
        "refreshToken": "refresh-me",
        "expiresAt": time.time() + 600,
        "userInfo": {"id": "user"},
        "provider": "cline",
    }
    updated_payload = {
        "idToken": "second-token",
        "refreshToken": "refresh-me",
        "expiresAt": time.time() + 1200,
        "userInfo": {"id": "user"},
        "provider": "cline",
    }
    _write_auth_payload(secrets_path, initial_payload)

    connector = ClineConnector(http_client, config, translation_service)
    await connector.initialize(secrets_path=secrets_path)

    # Update secrets file and bump mtime so connector notices the change.
    await asyncio.sleep(0.01)  # Ensure filesystem mtime granularity is exceeded
    _write_auth_payload(secrets_path, updated_payload)
    os.utime(secrets_path, None)

    chat_request = ChatRequest(
        model="cline/test",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=False,
    )

    with patch.object(
        OpenAIConnector,
        "chat_completions",
        new=AsyncMock(return_value=SimpleNamespace(ok=True)),
    ) as mock_super:
        result = await connector.chat_completions(
            chat_request,
            chat_request.messages,
            "cline/test",
        )

    assert result.ok
    mock_super.assert_awaited_once()
    assert connector.api_key == "workos:second-token"


@pytest.mark.asyncio
async def test_chat_completions_retries_after_401(
    http_client, config, translation_service, tmp_path
):
    """Connector should refresh and retry once after a 401."""
    secrets_path = tmp_path / "secrets.json"
    _write_auth_payload(
        secrets_path,
        {
            "idToken": "first-token",
            "refreshToken": "refresh",
            "expiresAt": time.time() + 600,
            "userInfo": {"id": "user"},
            "provider": "cline",
        },
    )
    connector = ClineConnector(http_client, config, translation_service)

    chat_request = ChatRequest(
        model="cline/test",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=False,
    )

    with (
        patch.object(
            ClineConnector, "_ensure_auth_token", new=AsyncMock()
        ) as mock_ensure,
        patch.object(
            OpenAIConnector,
            "chat_completions",
            new=AsyncMock(
                side_effect=[
                    HTTPException(status_code=401, detail="bad token"),
                    SimpleNamespace(ok=True),
                ]
            ),
        ),
    ):
        result = await connector.chat_completions(
            chat_request, chat_request.messages, "cline/test"
        )

    assert result.ok
    assert mock_ensure.await_args_list == [
        call(),
        call(force_reload=True, force_refresh=True),
    ]


@pytest.mark.asyncio
async def test_chat_completions_raises_after_double_401(
    http_client, config, translation_service, tmp_path
):
    """Connector should raise AuthenticationError when retries fail."""
    secrets_path = tmp_path / "secrets.json"
    _write_auth_payload(
        secrets_path,
        {
            "idToken": "first-token",
            "refreshToken": "refresh",
            "expiresAt": time.time() + 600,
            "userInfo": {"id": "user"},
            "provider": "cline",
        },
    )
    connector = ClineConnector(http_client, config, translation_service)

    chat_request = ChatRequest(
        model="cline/test",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=False,
    )

    with (
        patch.object(ClineConnector, "_ensure_auth_token", new=AsyncMock()),
        patch.object(
            OpenAIConnector,
            "chat_completions",
            new=AsyncMock(
                side_effect=[
                    HTTPException(status_code=401, detail="bad token"),
                    HTTPException(status_code=401, detail="still bad"),
                ]
            ),
        ),
        pytest.raises(AuthenticationError),
    ):
        await connector.chat_completions(
            chat_request, chat_request.messages, "cline/test"
        )
