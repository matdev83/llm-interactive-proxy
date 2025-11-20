from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from src.core.config.app_config import AppConfig, SessionConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.interfaces.middleware_application_manager_interface import (
    IMiddlewareApplicationManager,
)
from src.core.interfaces.response_parser_interface import IResponseParser
from src.core.services.response_processor_service import ResponseProcessor


class _DummyParser:
    def parse_response(self, response: Any) -> Any:
        return response

    def extract_content(self, response: Any) -> Any:
        return response.get("content")

    def extract_usage(self, response: Any) -> Any:
        return response.get("usage")

    def extract_metadata(self, response: Any) -> Any:
        return response.get("metadata")


class _DummyMiddlewareManager:
    async def apply_middleware(
        self,
        content: Any,
        middleware_list: list[Any] | None = None,
        is_streaming: bool = False,
        stop_event: Any = None,
        session_id: str = "",
        context: dict[str, Any] | None = None,
    ) -> Any:
        return content


class _DummyAppState:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def get_setting(self, key: str) -> Any:
        if key == "app_config":
            return self._config
        raise KeyError(key)


def _make_processor(config: AppConfig) -> ResponseProcessor:
    processor = ResponseProcessor(
        response_parser=cast(IResponseParser, _DummyParser()),
        middleware_application_manager=cast(
            IMiddlewareApplicationManager, _DummyMiddlewareManager()
        ),
    )
    processor._app_state = _DummyAppState(config)  # type: ignore[attr-defined]
    return processor


@pytest.mark.asyncio
async def test_angel_disabled_does_not_call_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AppConfig(session=SessionConfig(angel_model=None))
    processor = _make_processor(config)

    provider_called = False

    def _provider() -> None:
        nonlocal provider_called
        provider_called = True
        raise AssertionError("Angel backend should not be resolved when disabled")

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider",
        _provider,
        raising=False,
    )

    response = await processor.process_response(
        response={"content": "plain"},
        session_id="sess",
        context={
            "original_request": ChatRequest(
                model="fake",
                messages=[ChatMessage(role="user", content="hi")],
            )
        },
    )

    assert response.content == "plain"
    assert provider_called is False


@pytest.mark.asyncio
async def test_override_marker_never_reaches_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = AppConfig(session=SessionConfig(angel_model="fake_backend:guardian"))
    processor = _make_processor(config)

    class _Backend:
        def __init__(self) -> None:
            self.calls = 0

        async def chat_completions(
            self, request: ChatRequest, **_: Any
        ) -> SimpleNamespace:
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(
                    content="\n<angels_steering_message>Fix</angels_steering_message>\n"
                )
            return SimpleNamespace(content="<override_angel>True</override_angel>")

    backend = _Backend()

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider",
        lambda: SimpleNamespace(get_required_service=lambda _t: backend),
        raising=False,
    )

    result = await processor.process_response(
        response={"content": "original"},
        session_id="sess",
        context={
            "original_request": ChatRequest(
                model="fake_backend:primary",
                messages=[ChatMessage(role="user", content="Hello")],
            )
        },
    )

    assert result.content == "original"
    assert "override_angel" not in result.content
    assert backend.calls == 2


@pytest.mark.asyncio
async def test_client_never_sees_angel_xml(monkeypatch: pytest.MonkeyPatch) -> None:
    config = AppConfig(session=SessionConfig(angel_model="fake_backend:guardian"))
    processor = _make_processor(config)

    class _Backend:
        def __init__(self) -> None:
            self.calls = 0

        async def chat_completions(
            self, request: ChatRequest, **_: Any
        ) -> SimpleNamespace:
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(
                    content="\n<angels_steering_message>Improve answer</angels_steering_message>\n"
                )
            return SimpleNamespace(content="Corrected summary")

    backend = _Backend()
    monkeypatch.setattr(
        "src.core.di.services.get_service_provider",
        lambda: SimpleNamespace(get_required_service=lambda _t: backend),
        raising=False,
    )

    result = await processor.process_response(
        response={"content": "Bad draft"},
        session_id="sess",
        context={
            "original_request": ChatRequest(
                model="fake_backend:primary",
                messages=[ChatMessage(role="user", content="Task")],
            )
        },
    )

    assert "<angels_steering_message>" not in str(result.content)
    assert result.content == "Corrected summary"
    assert backend.calls == 2


@pytest.mark.asyncio
async def test_angel_frequency_can_skip_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    config = AppConfig(
        session=SessionConfig(angel_model="fake_backend:guardian", angel_frequency=4)
    )
    processor = _make_processor(config)

    class _Backend:
        async def chat_completions(self, *_, **__):
            pytest.fail("Angel should not run before reaching configured frequency")

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider",
        lambda: SimpleNamespace(get_required_service=lambda _t: _Backend()),
        raising=False,
    )

    result = await processor.process_response(
        response={"content": "First reply"},
        session_id="freq",
        context={
            "original_request": ChatRequest(
                model="fake_backend:primary",
                messages=[ChatMessage(role="user", content="Hello there")],
            )
        },
    )

    assert result.content == "First reply"
