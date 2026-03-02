from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from src.core.config.app_config import AppConfig, SessionConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.interfaces.response_parser_interface import IResponseParser
from src.core.services.quality_verifier_steering_store import (
    PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY,
)
from src.core.services.response_processor_service import ResponseProcessor
from src.core.services.streaming.content_accumulation_processor import (
    ContentAccumulationProcessor,
)
from src.core.services.streaming.stream_normalizer import StreamNormalizer


class _DummyParser:
    def parse_response(self, response: Any) -> Any:
        return response

    def extract_content(self, response: Any) -> Any:
        return response.get("content")

    def extract_usage(self, response: Any) -> Any:
        return response.get("usage")

    def extract_metadata(self, response: Any) -> Any:
        return response.get("metadata")


class _DummyAppState:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._settings: dict[str, Any] = {}

    def get_setting(self, key: str, default: Any = None) -> Any:
        if key == "app_config":
            return self._config
        return self._settings.get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        self._settings[key] = value

    def get_service(self, _t: Any) -> Any:
        return None


def _make_processor(app_state: _DummyAppState) -> ResponseProcessor:
    stream_normalizer = StreamNormalizer([ContentAccumulationProcessor()])
    processor = ResponseProcessor(
        response_parser=cast(IResponseParser, _DummyParser()),
        stream_normalizer=stream_normalizer,
    )
    processor._app_state = app_state  # type: ignore[attr-defined]
    return processor


@pytest.mark.asyncio
async def test_quality_verifier_disabled_does_not_call_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AppConfig(session=SessionConfig(quality_verifier_model=None))
    app_state = _DummyAppState(config)
    processor = _make_processor(app_state)

    provider_called = False

    def _provider() -> None:
        nonlocal provider_called
        provider_called = True
        pytest.fail("Backend service should not have been requested")

    monkeypatch.setattr("src.core.di.services.get_service_provider", _provider)

    original_request = ChatRequest(
        model="any",
        messages=[ChatMessage(role="user", content="Hello")],
    )
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=app_state,
        original_request=original_request,
        session_id="s1",
    )
    result = await processor.process_response(
        {"content": "World"},
        session_id="s1",
        context=context,
    )
    assert result.content == "World"
    assert provider_called is False


@pytest.mark.asyncio
async def test_quality_verifier_steering_is_private_and_does_not_modify_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AppConfig(
        session=SessionConfig(
            quality_verifier_model="demo", quality_verifier_frequency=1
        )
    )
    app_state = _DummyAppState(config)
    processor = _make_processor(app_state)

    class DummyBackendService:
        calls = 0

        async def chat_completions(self, req: Any, *args: Any, **kwargs: Any) -> Any:
            self.calls += 1
            return SimpleNamespace(content="<steering>Do Y instead</steering>")

    service = DummyBackendService()

    class DummyProvider:
        def get_required_service(self, t: Any) -> Any:
            return service

        def get_service(self, t: Any) -> Any:
            return None

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider", lambda: DummyProvider()
    )

    original_request = ChatRequest(
        model="any",
        messages=[ChatMessage(role="user", content="Hello")],
    )
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=app_state,
        original_request=original_request,
        session_id="s2",
    )

    result = await processor.process_response(
        {"content": "Initial"},
        session_id="s2",
        context=context,
    )

    assert str(result.content or "") == "Initial"

    await asyncio.sleep(0)
    assert service.calls == 1
    pending = app_state.get_setting(PENDING_QUALITY_VERIFIER_STEERING_SETTING_KEY, {})
    assert isinstance(pending, dict)
    assert "s2" in pending


@pytest.mark.asyncio
async def test_quality_verifier_frequency_can_skip_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AppConfig(
        session=SessionConfig(
            quality_verifier_model="demo", quality_verifier_frequency=10
        )
    )
    app_state = _DummyAppState(config)
    processor = _make_processor(app_state)

    class DummyBackendService:
        async def chat_completions(self, req: Any, *args: Any, **kwargs: Any) -> Any:
            pytest.fail("Backend should not be called due to frequency check")

    class DummyProvider:
        def get_required_service(self, t: Any) -> Any:
            return DummyBackendService()

        def get_service(self, t: Any) -> Any:
            return None

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider", lambda: DummyProvider()
    )

    original_request = ChatRequest(
        model="any",
        messages=[ChatMessage(role="user", content="Hello")],
    )
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=app_state,
        original_request=original_request,
        session_id="s3",
    )
    result = await processor.process_response(
        {"content": "First turn"},
        session_id="s3",
        context=context,
    )
    assert result.content == "First turn"
