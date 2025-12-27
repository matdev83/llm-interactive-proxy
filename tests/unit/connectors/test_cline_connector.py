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
from tests.utils.fake_clock import FakeClock, FakeClockContext
from fastapi import HTTPException
from src.connectors.cline import ClineConnector
from src.connectors.openai import OpenAIConnector
from src.connectors.utils.cline_auth_types import ClineTokenData
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
    async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
        secrets_path = tmp_path / "secrets.json"
        payload = {
            "idToken": "abc123",
            "refreshToken": "refresh-token",
            "expiresAt": clock.now() + 3600,
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
    async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
        secrets_path = tmp_path / "secrets.json"
        stored_payload = {
            "idToken": "expired-token",
            "refreshToken": "refresh-me",
            "expiresAt": clock.now() - 5,
            "userInfo": {"id": "user"},
            "provider": "cline",
        }
        refreshed_payload = ClineTokenData(
            idToken="new-token",
            refreshToken="refresh-me",
            expiresAt=clock.now() + 600,
            userInfo={"id": "user"},
            provider="cline",
        )

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
    async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
        auth_path = tmp_path / "codex" / "auth.json"
        auth_path.parent.mkdir(parents=True, exist_ok=True)
        expiry = clock.now() + 900
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

        refreshed_payload = ClineTokenData(
            idToken="converted-token",
            refreshToken="converted-refresh",
            expiresAt=expiry + 120,
            userInfo={"id": "cline-user"},
            provider="cline",
        )

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
    assert cline_payload == refreshed_payload.model_dump(by_alias=True)


@pytest.mark.asyncio
async def test_initialize_uses_vscode_secrets_when_available(
    http_client, config, translation_service, tmp_path
):
    """VSCode secret store should supply credentials if disk secrets are empty."""
    secrets_path = tmp_path / "cline" / "secrets.json"
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    secrets_path.write_text("{}", encoding="utf-8")

    vscode_payload = ClineTokenData(
        idToken="vscode-token",
        refreshToken="refresh-vscode",
        expiresAt=time.time() + 300,
        userInfo={"id": "vscode-user"},
        provider="cline",
    )

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
    async with FakeClockContext(FakeClock(initial_time=1000.0)) as clock:
        secrets_path = tmp_path / "secrets.json"
        initial_payload = {
            "idToken": "first-token",
            "refreshToken": "refresh-me",
            "expiresAt": clock.now() + 600,
            "userInfo": {"id": "user"},
            "provider": "cline",
        }
        updated_payload = {
            "idToken": "second-token",
            "refreshToken": "refresh-me",
            "expiresAt": clock.now() + 1200,
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
            incoming_headers={"User-Agent": "Cline VSCode Extension"},
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
            chat_request,
            chat_request.messages,
            "cline/test",
            incoming_headers={"User-Agent": "Cline VSCode Extension"},
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
            chat_request,
            chat_request.messages,
            "cline/test",
            incoming_headers={"User-Agent": "Cline VSCode Extension"},
        )


# Tests for Cline agent validation in cline_new.py
@pytest.mark.asyncio
async def test_validate_cline_agent_valid_user_agent(
    http_client, config, translation_service, tmp_path, caplog
):
    """Test validation passes with Cline in User-Agent."""
    secrets_path = tmp_path / "secrets.json"
    _write_auth_payload(
        secrets_path,
        {
            "idToken": "test-token",
            "refreshToken": "refresh",
            "expiresAt": time.time() + 600,
            "userInfo": {"id": "user"},
            "provider": "cline",
        },
    )

    connector = ClineConnector(http_client, config, translation_service)
    await connector.initialize(secrets_path=secrets_path)

    # Valid User-Agent with Cline
    headers = {"User-Agent": "Cline VSCode Extension"}
    connector._validate_cline_agent(headers)  # Should not raise


@pytest.mark.asyncio
async def test_validate_cline_agent_valid_x_title(
    http_client, config, translation_service, tmp_path, caplog
):
    """Test validation passes with Cline in X-Title."""
    secrets_path = tmp_path / "secrets.json"
    _write_auth_payload(
        secrets_path,
        {
            "idToken": "test-token",
            "refreshToken": "refresh",
            "expiresAt": time.time() + 600,
            "userInfo": {"id": "user"},
            "provider": "cline",
        },
    )

    connector = ClineConnector(http_client, config, translation_service)
    await connector.initialize(secrets_path=secrets_path)

    # Valid X-Title with Cline
    headers = {"X-Title": "Cline - AI Assistant"}
    connector._validate_cline_agent(headers)  # Should not raise


@pytest.mark.asyncio
async def test_validate_cline_agent_case_insensitive(
    http_client, config, translation_service, tmp_path, caplog
):
    """Test validation is case insensitive."""
    secrets_path = tmp_path / "secrets.json"
    _write_auth_payload(
        secrets_path,
        {
            "idToken": "test-token",
            "refreshToken": "refresh",
            "expiresAt": time.time() + 600,
            "userInfo": {"id": "user"},
            "provider": "cline",
        },
    )

    connector = ClineConnector(http_client, config, translation_service)
    await connector.initialize(secrets_path=secrets_path)

    # Test different case variations
    test_cases = [
        {"User-Agent": "CLINE vscode extension"},
        {"User-Agent": "Cline VSCode Extension"},
        {"User-Agent": "cLiNe assistant"},
        {"X-Title": "CLINE AI TOOL"},
        {"X-Title": "cline-powered editor"},
    ]

    for headers in test_cases:
        connector._validate_cline_agent(headers)  # Should not raise


@pytest.mark.asyncio
async def test_validate_cline_agent_invalid_user_agent(
    http_client, config, translation_service, tmp_path, caplog
):
    """Test validation fails without Cline in User-Agent or X-Title."""
    secrets_path = tmp_path / "secrets.json"
    _write_auth_payload(
        secrets_path,
        {
            "idToken": "test-token",
            "refreshToken": "refresh",
            "expiresAt": time.time() + 600,
            "userInfo": {"id": "user"},
            "provider": "cline",
        },
    )

    connector = ClineConnector(http_client, config, translation_service)
    await connector.initialize(secrets_path=secrets_path)

    # Invalid headers without Cline
    headers = {"User-Agent": "VSCode Extension", "X-Title": "AI Assistant"}

    with pytest.raises(HTTPException) as exc_info:
        connector._validate_cline_agent(headers)

    assert exc_info.value.status_code == 403
    assert "Forbidden" in exc_info.value.detail
    assert "Cline clients" in exc_info.value.detail


@pytest.mark.asyncio
async def test_validate_cline_agent_logs_warning(
    http_client, config, translation_service, tmp_path, caplog
):
    """Test that rejected requests generate warning logs."""
    secrets_path = tmp_path / "secrets.json"
    _write_auth_payload(
        secrets_path,
        {
            "idToken": "test-token",
            "refreshToken": "refresh",
            "expiresAt": time.time() + 600,
            "userInfo": {"id": "user"},
            "provider": "cline",
        },
    )

    connector = ClineConnector(http_client, config, translation_service)
    await connector.initialize(secrets_path=secrets_path)

    # Invalid headers
    headers = {"User-Agent": "VSCode Extension", "X-Title": "AI Assistant"}

    with pytest.raises(HTTPException):
        connector._validate_cline_agent(headers)

    # Check warning was logged
    warning_logs = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warning_logs) == 1
    assert "Rejected request" in warning_logs[0].message
    assert "missing 'Cline'" in warning_logs[0].message
    assert "--enable-cline-backend-debugging-override" in warning_logs[0].message


@pytest.mark.asyncio
async def test_chat_completions_with_debug_override(
    http_client, config, translation_service, tmp_path, caplog
):
    """Test that debug override flag bypasses validation."""
    secrets_path = tmp_path / "secrets.json"
    _write_auth_payload(
        secrets_path,
        {
            "idToken": "test-token",
            "refreshToken": "refresh",
            "expiresAt": time.time() + 600,
            "userInfo": {"id": "user"},
            "provider": "cline",
        },
    )

    connector = ClineConnector(http_client, config, translation_service)
    await connector.initialize(
        secrets_path=secrets_path, enable_cline_backend_debugging_override=True
    )

    chat_request = ChatRequest(
        model="cline/test",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=False,
    )

    # Even with invalid headers, should not raise due to debug override
    incoming_headers = {"User-Agent": "VSCode Extension", "X-Title": "AI Assistant"}

    with patch.object(
        OpenAIConnector,
        "chat_completions",
        new=AsyncMock(return_value=SimpleNamespace(ok=True)),
    ):
        await connector.chat_completions(
            chat_request,
            chat_request.messages,
            "cline/test",
            incoming_headers=incoming_headers,
        )

        # Should not log warning since override is enabled
        warning_logs = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warning_logs) == 0


@pytest.mark.asyncio
async def test_chat_completions_without_debug_override(
    http_client, config, translation_service, tmp_path, caplog
):
    """Test that requests without debug override are validated."""
    secrets_path = tmp_path / "secrets.json"
    _write_auth_payload(
        secrets_path,
        {
            "idToken": "test-token",
            "refreshToken": "refresh",
            "expiresAt": time.time() + 600,
            "userInfo": {"id": "user"},
            "provider": "cline",
        },
    )

    connector = ClineConnector(http_client, config, translation_service)
    await connector.initialize(secrets_path=secrets_path)  # No override

    chat_request = ChatRequest(
        model="cline/test",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=False,
    )

    # Invalid headers should trigger validation error
    incoming_headers = {"User-Agent": "VSCode Extension", "X-Title": "AI Assistant"}

    with pytest.raises(HTTPException) as exc_info:
        await connector.chat_completions(
            chat_request,
            chat_request.messages,
            "cline/test",
            incoming_headers=incoming_headers,
        )

    assert exc_info.value.status_code == 403

    # Should log warning
    warning_logs = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warning_logs) == 1


@pytest.mark.asyncio
async def test_chat_completions_valid_cline_agent(
    http_client, config, translation_service, tmp_path, caplog
):
    """Test that valid Cline agents pass validation and make successful requests."""
    secrets_path = tmp_path / "secrets.json"
    _write_auth_payload(
        secrets_path,
        {
            "idToken": "test-token",
            "refreshToken": "refresh",
            "expiresAt": time.time() + 600,
            "userInfo": {"id": "user"},
            "provider": "cline",
        },
    )

    connector = ClineConnector(http_client, config, translation_service)
    await connector.initialize(secrets_path=secrets_path)

    chat_request = ChatRequest(
        model="cline/test",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=False,
    )

    # Valid Cline headers
    incoming_headers = {"User-Agent": "Cline VSCode Extension"}

    with patch.object(
        OpenAIConnector,
        "chat_completions",
        new=AsyncMock(return_value=SimpleNamespace(ok=True)),
    ):
        await connector.chat_completions(
            chat_request,
            chat_request.messages,
            "cline/test",
            incoming_headers=incoming_headers,
        )

        # Should not log warnings
        warning_logs = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warning_logs) == 0


@pytest.mark.asyncio
async def test_validate_cline_agent_empty_headers(
    http_client, config, translation_service, tmp_path, caplog
):
    """Test validation with empty headers."""
    secrets_path = tmp_path / "secrets.json"
    _write_auth_payload(
        secrets_path,
        {
            "idToken": "test-token",
            "refreshToken": "refresh",
            "expiresAt": time.time() + 600,
            "userInfo": {"id": "user"},
            "provider": "cline",
        },
    )

    connector = ClineConnector(http_client, config, translation_service)
    await connector.initialize(secrets_path=secrets_path)

    # Empty headers
    headers = {}

    with pytest.raises(HTTPException) as exc_info:
        connector._validate_cline_agent(headers)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_validate_cline_agent_mixed_case_match(
    http_client, config, translation_service, tmp_path, caplog
):
    """Test validation with mixed case Cline in both headers."""
    secrets_path = tmp_path / "secrets.json"
    _write_auth_payload(
        secrets_path,
        {
            "idToken": "test-token",
            "refreshToken": "refresh",
            "expiresAt": time.time() + 600,
            "userInfo": {"id": "user"},
            "provider": "cline",
        },
    )

    connector = ClineConnector(http_client, config, translation_service)
    await connector.initialize(secrets_path=secrets_path)

    # Both headers have Cline in different cases
    headers = {"User-Agent": "cLiNe VsCoDe ExTeNsIoN", "X-Title": "CLINE AI Assistant"}
    connector._validate_cline_agent(headers)  # Should not raise


@pytest.mark.asyncio
async def test_debug_override_configuration_from_kwargs(
    http_client, config, translation_service, tmp_path, caplog
):
    """Test that debug override can be configured via kwargs."""
    secrets_path = tmp_path / "secrets.json"
    _write_auth_payload(
        secrets_path,
        {
            "idToken": "test-token",
            "refreshToken": "refresh",
            "expiresAt": time.time() + 600,
            "userInfo": {"id": "user"},
            "provider": "cline",
        },
    )

    # Test configuration via kwargs
    connector = ClineConnector(http_client, config, translation_service)
    await connector.initialize(
        secrets_path=secrets_path, enable_cline_backend_debugging_override=True
    )

    assert connector._enable_cline_backend_debugging_override is True

    chat_request = ChatRequest(
        model="cline/test",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=False,
    )

    # Should not validate with override enabled
    incoming_headers = {"User-Agent": "Non-Cline Client"}

    with patch.object(
        OpenAIConnector,
        "chat_completions",
        new=AsyncMock(return_value=SimpleNamespace(ok=True)),
    ):
        await connector.chat_completions(
            chat_request,
            chat_request.messages,
            "cline/test",
            incoming_headers=incoming_headers,
        )

        # Should succeed without validation error
        # Note: result.ok assertion removed as result is not used


class TestClineDataEnvelopeUnwrapping:
    """Tests for Cline's non-standard response format handling."""

    def test_unwraps_data_envelope_with_choices(self, config, translation_service):
        """Test that a response wrapped in 'data' envelope is properly unwrapped."""
        http_client = AsyncMock()
        connector = ClineConnector(http_client, config, translation_service)

        wrapped_response = {
            "data": {
                "id": "chatcmpl-123",
                "object": "chat.completion",
                "created": 1234567890,
                "model": "x-ai/grok-code-fast-1",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Hello! I'm ready to help.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                    "total_tokens": 30,
                },
            }
        }

        unwrapped = connector._unwrap_cline_data_envelope(wrapped_response)

        assert unwrapped["id"] == "chatcmpl-123"
        assert unwrapped["model"] == "x-ai/grok-code-fast-1"
        assert len(unwrapped["choices"]) == 1
        assert (
            unwrapped["choices"][0]["message"]["content"] == "Hello! I'm ready to help."
        )
        assert unwrapped["usage"]["total_tokens"] == 30

    def test_does_not_unwrap_non_openai_data_envelope(
        self, config, translation_service
    ):
        """Test that unrelated 'data' keys are not mistakenly unwrapped."""
        http_client = AsyncMock()
        connector = ClineConnector(http_client, config, translation_service)

        # If the 'data' value doesn't look like an OpenAI response, don't unwrap
        non_openai_data = {
            "data": {"some_field": "value"},  # No 'choices', 'id', or 'model'
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Direct response"},
                    "finish_reason": "stop",
                }
            ],
        }

        unwrapped = connector._unwrap_cline_data_envelope(non_openai_data)

        # Should not unwrap since 'data' doesn't look like OpenAI response
        assert "choices" in unwrapped
        assert unwrapped["choices"][0]["message"]["content"] == "Direct response"

    def test_does_not_modify_standard_openai_response(
        self, config, translation_service
    ):
        """Test that standard OpenAI responses (without 'data' envelope) pass through unchanged."""
        http_client = AsyncMock()
        connector = ClineConnector(http_client, config, translation_service)

        standard_response = {
            "id": "chatcmpl-456",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Standard response",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 5,
                "completion_tokens": 10,
                "total_tokens": 15,
            },
        }

        unwrapped = connector._unwrap_cline_data_envelope(standard_response)

        assert unwrapped is standard_response  # Should be the same object
        assert unwrapped["id"] == "chatcmpl-456"
