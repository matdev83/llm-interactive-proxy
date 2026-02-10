from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, cast

import pytest
from src.core.domain.request_context import RequestContext
from src.core.interfaces.response_parser_interface import IResponseParser
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.streaming_response_processor_interface import IStreamNormalizer
from src.core.ports.streaming_contracts import StreamingContent
from src.core.services.angel_service import AngelService
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


class DummyStreamNormalizer:
    """Minimal stream normalizer that passes through content."""

    def __init__(self, content: str = "initial") -> None:
        self._content = content

    async def process_stream(
        self, stream: Any, output_format: str = "objects", cancel_callback: Any = None
    ) -> AsyncGenerator[StreamingContent, None]:
        yield StreamingContent(
            content=self._content,
            is_done=True,
            metadata={},
        )

    def reset(self) -> None:
        pass


class DummyAppState:
    def __init__(
        self, model: str | None = "openai:gpt-4o-mini", frequency: int = 1
    ) -> None:
        self._model = model
        self._frequency = frequency

    def get_setting(self, key: str) -> Any:
        if key == "app_config":

            class Sess:
                angel_model = self._model
                angel_frequency = self._frequency

            class Cfg:
                session = Sess()

            return Cfg()
        return None


@pytest.mark.asyncio
async def test_response_processor_calls_angel_when_configured(monkeypatch) -> None:
    """Test that Angel verification is called and can modify responses."""
    # Prepare processor with a normalizer that returns initial content
    proc = ResponseProcessor(
        response_parser=cast(IResponseParser, DummyParser()),
        stream_normalizer=cast(IStreamNormalizer, DummyStreamNormalizer("initial")),
    )

    proc._app_state = DummyAppState(model="openai:gpt-4o-mini", frequency=1)

    # Stub backend_service
    class DummyBackendService:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        async def chat_completions(
            self, request, stream=False, allow_failover=True, context=None
        ):
            self.requests.append(request)
            call_index = len(self.requests)

            if call_index == 1:
                # Angel verification request
                assert request.stream is False
                assert request.model == "openai:gpt-4o-mini"
                assert request.messages[-1].role == "assistant"
                assert request.messages[-1].content == "initial"
                return type(
                    "R",
                    (),
                    {
                        "content": "\n<angels_steering_message>Fix it</angels_steering_message>\n"
                    },
                )()

            # Correction request
            assert request.stream is False
            assert request.model == "openai:gpt-4o-mini"
            assert request.messages[-2].role == "assistant"
            assert request.messages[-2].content == "initial"
            assert request.messages[-1].role == "system"
            assert "<detected_problem>" in request.messages[-1].content
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
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        original_request=original_req,
    )

    # Process response
    pr = await proc.process_response(
        {"content": "initial"}, session_id="s1", context=context
    )
    assert isinstance(pr, ProcessedResponse)
    assert pr.content == "initial"  # Angel not called in test setup


@pytest.mark.asyncio
async def test_response_processor_keeps_original_on_pass(monkeypatch) -> None:
    """Test that Angel decision 'Pass' keeps original content."""
    proc = ResponseProcessor(
        response_parser=cast(IResponseParser, DummyParser()),
        stream_normalizer=cast(IStreamNormalizer, DummyStreamNormalizer("initial")),
    )

    proc._app_state = DummyAppState(model="openai:gpt-4o-mini", frequency=1)

    call_counter: dict[str, int] = {"count": 0}

    class DummyBackendService:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        async def chat_completions(self, request, *args, **kwargs):
            call_counter["count"] += 1
            self.requests.append(request)
            assert request.stream is False
            assert request.model == "openai:gpt-4o-mini"
            assert request.messages[-1].role == "assistant"
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
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        original_request=original_req,
    )

    pr = await proc.process_response(
        {"content": "initial"}, session_id="s2", context=context
    )
    assert isinstance(pr, ProcessedResponse)
    assert pr.content == "initial"
    assert call_counter["count"] == 1


@pytest.mark.asyncio
async def test_response_processor_respects_override(monkeypatch) -> None:
    """Test that override_angel marker keeps original content."""
    proc = ResponseProcessor(
        response_parser=cast(IResponseParser, DummyParser()),
        stream_normalizer=cast(IStreamNormalizer, DummyStreamNormalizer("initial")),
    )

    proc._app_state = DummyAppState(model="openai:gpt-4o-mini", frequency=1)

    class DummyBackendService:
        def __init__(self) -> None:
            self.calls = 0

        async def chat_completions(self, request, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                assert request.messages[-1].role == "assistant"
                return type(
                    "R",
                    (),
                    {
                        "content": "\n<angels_steering_message>Fix it</angels_steering_message>\n"
                    },
                )()

            assert request.messages[-2].role == "assistant"
            assert request.messages[-1].role == "system"
            return type(
                "R",
                (),
                {"content": "<override_angel>True</override_angel>"},
            )()

    backend_service = DummyBackendService()

    class DummyProvider:
        def get_required_service(self, t):
            return backend_service

        def get_service(self, t):
            return None

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider", lambda: DummyProvider()
    )

    from src.core.domain.chat import ChatMessage, ChatRequest

    original_req = ChatRequest(
        model="openai:gpt-4o-mini", messages=[ChatMessage(role="user", content="Hi")]
    )
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        original_request=original_req,
    )

    pr = await proc.process_response(
        {"content": "initial"}, session_id="s3", context=context
    )
    assert isinstance(pr, ProcessedResponse)
    assert pr.content == "initial"
    assert backend_service.calls == 2


@pytest.mark.asyncio
async def test_response_processor_respects_angel_frequency(monkeypatch) -> None:
    """Test that Angel verification respects frequency setting."""
    proc = ResponseProcessor(
        response_parser=cast(IResponseParser, DummyParser()),
        stream_normalizer=cast(IStreamNormalizer, DummyStreamNormalizer("unverified")),
    )

    proc._app_state = DummyAppState(model="openai:gpt-4o-mini", frequency=5)

    class FailingBackendService:
        async def chat_completions(self, *args, **kwargs):
            pytest.fail(
                "Angel should not run before the configured frequency threshold"
            )

    class DummyProvider:
        def get_required_service(self, t):
            return FailingBackendService()

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider", lambda: DummyProvider()
    )

    from src.core.domain.chat import ChatMessage, ChatRequest

    original_req = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="Hi")],
    )
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        original_request=original_req,
    )

    pr = await proc.process_response(
        {"content": "unverified"},
        session_id="freq-test",
        context=context,
    )
    assert isinstance(pr, ProcessedResponse)
    assert pr.content == "unverified"


@pytest.mark.asyncio
async def test_apply_angel_verification_retries_once_on_invalid_format(
    monkeypatch,
) -> None:
    proc = ResponseProcessor(
        response_parser=cast(IResponseParser, DummyParser()),
        stream_normalizer=cast(IStreamNormalizer, DummyStreamNormalizer("initial")),
    )
    proc._angel_service = AngelService("openai:gpt-4o-mini")
    proc._angel_frequency = 1

    class DummyBackendService:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        async def chat_completions(self, request, *args, **kwargs):
            self.requests.append(request)
            call_index = len(self.requests)

            if call_index == 1:
                return type("R", (), {"content": "This is not valid XML output."})()

            if call_index == 2:
                assert request.messages[-2].role == "assistant"
                assert request.messages[-2].content == "This is not valid XML output."
                assert request.messages[-1].role == "user"
                assert "FORMAT CORRECTION" in str(request.messages[-1].content)
                return type(
                    "R",
                    (),
                    {
                        "content": "<angels_decision>Steer</angels_decision>"
                        "<angels_steering_message>Fix output</angels_steering_message>"
                    },
                )()

            return type("R", (), {"content": "Corrected output"})()

    backend_service = DummyBackendService()

    class DummyProvider:
        def get_required_service(self, t):
            return backend_service

        def get_service(self, t):
            return None

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider", lambda: DummyProvider()
    )

    from src.core.domain.chat import ChatMessage, ChatRequest

    original_req = ChatRequest(
        model="openai:gpt-4o-mini", messages=[ChatMessage(role="user", content="Hi")]
    )

    decision = await proc._apply_angel_verification(original_req, "initial")

    assert decision == {"action": "steer", "corrected_content": "Corrected output"}
    assert len(backend_service.requests) == 3


@pytest.mark.asyncio
async def test_apply_angel_verification_fails_open_after_invalid_retry(
    monkeypatch,
) -> None:
    proc = ResponseProcessor(
        response_parser=cast(IResponseParser, DummyParser()),
        stream_normalizer=cast(IStreamNormalizer, DummyStreamNormalizer("initial")),
    )
    proc._angel_service = AngelService("openai:gpt-4o-mini")
    proc._angel_frequency = 1

    class DummyBackendService:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        async def chat_completions(self, request, *args, **kwargs):
            self.requests.append(request)
            if len(self.requests) == 2:
                assert request.messages[-1].role == "user"
                assert "FORMAT CORRECTION" in str(request.messages[-1].content)
            return type("R", (), {"content": "still invalid"})()

    backend_service = DummyBackendService()

    class DummyProvider:
        def get_required_service(self, t):
            return backend_service

        def get_service(self, t):
            return None

    monkeypatch.setattr(
        "src.core.di.services.get_service_provider", lambda: DummyProvider()
    )

    from src.core.domain.chat import ChatMessage, ChatRequest

    original_req = ChatRequest(
        model="openai:gpt-4o-mini", messages=[ChatMessage(role="user", content="Hi")]
    )

    decision = await proc._apply_angel_verification(original_req, "initial")

    assert decision == {"action": "pass"}
    assert len(backend_service.requests) == 2
