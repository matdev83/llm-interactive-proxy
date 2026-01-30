"""Unit tests for fingerprint_request_transformer helpers."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.services.fingerprint_request_transformer import (
    apply_fingerprint_transforms,
)
from src.core.services.secure_state_service import StateAccessProxy


class _ServiceProvider:
    def __init__(self, service: Any | None) -> None:
        self._service = service

    def get_service(self, _interface: Any) -> Any | None:
        return self._service


class _AppState:
    def __init__(self, *, service_provider: Any | None, app_config: Any | None) -> None:
        self.service_provider = service_provider
        self.app_config = app_config

    def get_setting(self, _key: str) -> Any:
        raise RuntimeError("direct access not allowed")


@pytest.mark.asyncio
async def test_apply_fingerprint_uses_service_provider_config() -> None:
    config = AppConfig({"auth": {"redact_api_keys_in_prompts": False}})
    app_state_service = MagicMock(spec=IApplicationState)
    app_state_service.get_setting.return_value = config

    app_state = _AppState(
        service_provider=_ServiceProvider(app_state_service), app_config=None
    )

    context = RequestContext(headers={}, cookies={}, state=None, app_state=app_state)
    request = ChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="hello")],
    )

    result = await apply_fingerprint_transforms(request, context=context)

    assert result is request
    app_state_service.get_setting.assert_called_once_with("app_config")


@pytest.mark.asyncio
async def test_apply_fingerprint_uses_app_state_fallback_config() -> None:
    config = AppConfig({"auth": {"redact_api_keys_in_prompts": False}})
    app_state = _AppState(service_provider=None, app_config=config)

    context = RequestContext(headers={}, cookies={}, state=None, app_state=app_state)
    request = ChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="hello")],
    )

    result = await apply_fingerprint_transforms(request, context=context)

    assert result is request


@pytest.mark.asyncio
async def test_apply_fingerprint_avoids_state_access_violation() -> None:
    config = AppConfig({"auth": {"redact_api_keys_in_prompts": False}})
    app_state_service = MagicMock(spec=IApplicationState)
    app_state_service.get_setting.return_value = config

    target_state = _AppState(
        service_provider=_ServiceProvider(app_state_service), app_config=None
    )
    proxy_state = StateAccessProxy(target_state, [IApplicationState])

    context = RequestContext(headers={}, cookies={}, state=None, app_state=proxy_state)
    request = ChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="hello")],
    )

    result = await apply_fingerprint_transforms(request, context=context)

    assert result is request
    app_state_service.get_setting.assert_called_once_with("app_config")
