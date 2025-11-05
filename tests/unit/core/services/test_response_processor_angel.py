from __future__ import annotations

from typing import Any, cast

import pytest
from src.core.interfaces.middleware_application_manager_interface import (
    IMiddlewareApplicationManager,
)
from src.core.interfaces.response_parser_interface import IResponseParser
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.response_processor_service import ResponseProcessor


class DummyParser:
    def parse_response(self, response: Any) -> Any:
        return response

    def extract_content(self, response: Any) -> Any:
        return response.get("content")

    def extract_usage(self, response: Any) -> Any:
        return response.get("usage")

    def extract_metadata(self, response: Any) -> Any:
        return response.get("metadata")


class DummyMiddlewareManager:
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


@pytest.mark.asyncio
async def test_response_processor_calls_angel_when_configured(monkeypatch) -> None:
    # Prepare processor
    proc = ResponseProcessor(
        response_parser=cast(IResponseParser, DummyParser()),
        middleware_application_manager=cast(
            IMiddlewareApplicationManager, DummyMiddlewareManager()
        ),
    )

    # Fake app_state with angel_model
    class DummyAppState:
        def get_setting(self, key: str) -> Any:
            if key == "app_config":

                class S:
                    angel_model = None

                class Sess:
                    angel_model = "openai:gpt-4o-mini"

                class Cfg:
                    session = Sess()

                return Cfg()
            return None

    proc._app_state = DummyAppState()

    # Stub backend_service
    class DummyBackendService:
        async def chat_completions(
            self, request, stream=False, allow_failover=True, context=None
        ):
            # First call returns steering, second call returns corrected text
            if any(msg.role == "assistant" for msg in request.messages):
                # Angel response
                return type(
                    "R",
                    (),
                    {
                        "content": "\n<angels_steering_message>Fix it</angels_steering_message>\n"
                    },
                )()
            else:
                # Correction response without override
                return type("R", (), {"content": "Corrected output"})()

    class DummyProvider:
        def get_required_service(self, t):
            return DummyBackendService()

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider", lambda: DummyProvider()
    )

    # Original request context
    from src.core.domain.chat import ChatMessage, ChatRequest

    original_req = ChatRequest(
        model="openai:gpt-4o-mini", messages=[ChatMessage(role="user", content="Hi")]
    )
    context = {"original_request": original_req}

    # Process response
    pr = await proc.process_response(
        {"content": "initial"}, session_id="s1", context=context
    )
    assert isinstance(pr, ProcessedResponse)
    assert pr.content == "Corrected output"


@pytest.mark.asyncio
async def test_response_processor_keeps_original_on_pass(monkeypatch) -> None:
    proc = ResponseProcessor(
        response_parser=cast(IResponseParser, DummyParser()),
        middleware_application_manager=cast(
            IMiddlewareApplicationManager, DummyMiddlewareManager()
        ),
    )

    class DummyAppState:
        def get_setting(self, key: str) -> Any:
            if key == "app_config":

                class Sess:
                    angel_model = "openai:gpt-4o-mini"

                class Cfg:
                    session = Sess()

                return Cfg()
            return None

    proc._app_state = DummyAppState()

    call_counter: dict[str, int] = {"count": 0}

    class DummyBackendService:
        async def chat_completions(self, request, *args, **kwargs):
            call_counter["count"] += 1
            assert any(msg.role == "assistant" for msg in request.messages)
            return type(
                "R",
                (),
                {"content": "<angels_decision>Pass</angels_decision>"},
            )()

    class DummyProvider:
        def get_required_service(self, t):
            return DummyBackendService()

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider", lambda: DummyProvider()
    )

    from src.core.domain.chat import ChatMessage, ChatRequest

    original_req = ChatRequest(
        model="openai:gpt-4o-mini", messages=[ChatMessage(role="user", content="Hi")]
    )
    context = {"original_request": original_req}

    pr = await proc.process_response(
        {"content": "initial"}, session_id="s2", context=context
    )
    assert isinstance(pr, ProcessedResponse)
    assert pr.content == "initial"
    assert call_counter["count"] == 1


@pytest.mark.asyncio
async def test_response_processor_respects_override(monkeypatch) -> None:
    proc = ResponseProcessor(
        response_parser=cast(IResponseParser, DummyParser()),
        middleware_application_manager=cast(
            IMiddlewareApplicationManager, DummyMiddlewareManager()
        ),
    )

    class DummyAppState:
        def get_setting(self, key: str) -> Any:
            if key == "app_config":

                class Sess:
                    angel_model = "openai:gpt-4o-mini"

                class Cfg:
                    session = Sess()

                return Cfg()
            return None

    proc._app_state = DummyAppState()

    class DummyBackendService:
        def __init__(self) -> None:
            self.calls = 0

        async def chat_completions(self, request, *args, **kwargs):
            self.calls += 1
            if any(msg.role == "assistant" for msg in request.messages):
                return type(
                    "R",
                    (),
                    {
                        "content": "\n<angels_steering_message>Fix it</angels_steering_message>\n"
                    },
                )()
            return type(
                "R",
                (),
                {"content": "<override_angel>True</override_angel>"},
            )()

    backend_service = DummyBackendService()

    class DummyProvider:
        def get_required_service(self, t):
            return backend_service

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider", lambda: DummyProvider()
    )

    from src.core.domain.chat import ChatMessage, ChatRequest

    original_req = ChatRequest(
        model="openai:gpt-4o-mini", messages=[ChatMessage(role="user", content="Hi")]
    )
    context = {"original_request": original_req}

    pr = await proc.process_response(
        {"content": "initial"}, session_id="s3", context=context
    )
    assert isinstance(pr, ProcessedResponse)
    assert pr.content == "initial"
    assert backend_service.calls == 2
