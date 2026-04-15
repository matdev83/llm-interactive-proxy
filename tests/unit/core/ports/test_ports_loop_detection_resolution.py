"""Resolution of ports streaming pipeline loop detection (opt-in vs session default)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from src.core.config.app_config import AppConfig
from src.core.config.models.session import SessionConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.ports import streaming_integration as streaming_integration


def _minimal_request(**kwargs: Any) -> CanonicalChatRequest:
    return CanonicalChatRequest(
        model="m",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
        **kwargs,
    )


def test_explicit_false_overrides_request_true() -> None:
    req = _minimal_request(streaming_loop_detection_enabled=True)
    assert not streaming_integration._resolve_ports_streaming_loop_detection_enabled(
        explicit=False,
        domain_request=req,
    )


def test_explicit_true_overrides_request_false() -> None:
    req = _minimal_request(streaming_loop_detection_enabled=False)
    assert streaming_integration._resolve_ports_streaming_loop_detection_enabled(
        explicit=True,
        domain_request=req,
    )


def test_request_level_true_when_explicit_none() -> None:
    req = _minimal_request(streaming_loop_detection_enabled=True)
    assert streaming_integration._resolve_ports_streaming_loop_detection_enabled(
        explicit=None,
        domain_request=req,
    )


def test_request_level_false_when_explicit_none() -> None:
    req = _minimal_request(streaming_loop_detection_enabled=False)
    assert not streaming_integration._resolve_ports_streaming_loop_detection_enabled(
        explicit=None,
        domain_request=req,
    )


def test_falls_back_to_app_config_session(monkeypatch: pytest.MonkeyPatch) -> None:
    req = _minimal_request()
    provider = MagicMock()
    app_config = AppConfig(session=SessionConfig(streaming_loop_detection_enabled=True))
    provider.get_service.return_value = app_config
    monkeypatch.setattr(
        "src.core.di.services.get_or_build_service_provider",
        lambda: provider,
    )
    assert streaming_integration._resolve_ports_streaming_loop_detection_enabled(
        explicit=None,
        domain_request=req,
    )


def test_fails_open_false_when_di_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    req = _minimal_request()

    def _boom() -> MagicMock:
        raise RuntimeError("no di")

    monkeypatch.setattr(
        "src.core.di.services.get_or_build_service_provider",
        _boom,
    )
    assert not streaming_integration._resolve_ports_streaming_loop_detection_enabled(
        explicit=None,
        domain_request=req,
    )
