from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic.types import JsonValue
from src.core.config.app_config import AppConfig, SessionConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.response_parser_interface import IResponseParser
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.quality_verifier_service import (
    get_quality_verifier_prompt_loader,
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


class _StubBackendProcessor:
    def __init__(
        self, factory: Callable[[], ResponseEnvelope | StreamingResponseEnvelope]
    ):
        self._factory = factory
        self.calls: list[ChatRequest] = []

    async def process_backend_request(
        self,
        request: ChatRequest,
        session_id: str,
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        self.calls.append(request)
        return self._factory()


class _FakeBackendService:
    def __init__(
        self,
        *,
        corrected_text: str,
        steering_message: str = "Re-evaluate your answer",
        decision: str = "steer",
        override: bool = False,
    ) -> None:
        self.corrected_text = corrected_text
        self.steering_message = steering_message
        self.decision = decision
        self.override = override
        self.requests: list[ChatRequest] = []

    async def chat_completions(
        self,
        request: ChatRequest,
        stream: bool = False,
        allow_failover: bool = True,
        context: Any | None = None,
    ) -> SimpleNamespace:
        self.requests.append(request)
        first_message = request.messages[0]
        if (
            first_message.role == "system"
            and first_message.content
            == get_quality_verifier_prompt_loader().quality_verifier_prompt
        ):
            if self.decision.lower() == "pass":
                content = "<quality_verifier_decision>Pass</quality_verifier_decision>"
            else:
                content = (
                    "\n<quality_verifier_decision>Steer</quality_verifier_decision>\n"
                    f"<quality_verifier_steering_message>{self.steering_message}</quality_verifier_steering_message>\n"
                )
            return SimpleNamespace(content=content)

        if self.override:
            return SimpleNamespace(
                content="<override_quality_verifier>True</override_quality_verifier>"
            )
        return SimpleNamespace(content=self.corrected_text)

    def compute_identity(self, message: ChatMessage) -> str:
        """Mock implementation of compute_identity for INonForwardableMessageIdentityService."""
        import hashlib

        content = str(message.content) if message.content else ""
        return hashlib.sha256(content.encode()).hexdigest()

    def reset(self) -> None:
        """Mock implementation of reset for ILoopDetector."""

    def is_enabled(self) -> bool:
        """Mock implementation of is_enabled for ILoopDetector."""
        return False

    def process_chunk(self, chunk: str) -> Any:
        """Mock implementation of process_chunk for ILoopDetector."""
        return None

    def get_loop_history(self) -> list:
        """Mock implementation of get_loop_history for ILoopDetector."""
        return []

    def get_current_state(self) -> Any:
        """Mock implementation of get_current_state for ILoopDetector."""
        return None

    def get_stats(self) -> Any:
        """Mock implementation of get_stats for ILoopDetector."""
        return None

    async def check_for_loops(self, content: str) -> Any:
        """Mock implementation of check_for_loops for ILoopDetector."""
        from src.core.interfaces.loop_detector_interface import LoopDetectionResult

        return LoopDetectionResult(has_loop=False)

    async def tag_identities(
        self,
        session_id: str,
        identities: list,
        *,
        scope: Any,
        reason: str,
    ) -> None:
        """Mock implementation of tag_identities for INonForwardableMessageRegistry."""

    async def is_tagged(
        self,
        session_id: str,
        identity: str,
        *,
        scope: Any,
    ) -> bool:
        """Mock implementation of is_tagged for INonForwardableMessageRegistry."""
        return False


class _DummyAppState:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def get_setting(self, key: str) -> Any:
        if key == "app_config":
            return self._config
        raise KeyError(key)


def _make_response_processor(config: AppConfig) -> ResponseProcessor:
    """Create a ResponseProcessor using the unified pipeline architecture."""
    stream_normalizer = StreamNormalizer([ContentAccumulationProcessor()])
    processor = ResponseProcessor(
        response_parser=cast(IResponseParser, _DummyParser()),
        stream_normalizer=stream_normalizer,
    )
    processor._app_state = _DummyAppState(config)  # type: ignore[attr-defined]
    return processor


def _make_context(config: AppConfig) -> RequestContext:
    extensions: dict[str, JsonValue] = {}
    if (
        config.session
        and hasattr(config.session, "quality_verifier_model")
        and config.session.quality_verifier_model
    ):
        extensions["quality_verifier_model"] = config.session.quality_verifier_model
    if config.session and hasattr(config.session, "quality_verifier_frequency"):
        extensions["quality_verifier_frequency"] = (
            config.session.quality_verifier_frequency
        )
    return RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=_DummyAppState(config),
        client_host=None,
        session_id=None,
        agent=None,
        original_request=None,
        extensions=extensions,
    )


def _make_mock_provider(backend_service: _FakeBackendService) -> Any:
    """Create a mock provider that returns the fake backend service."""

    class _Provider:
        def get_required_service(self, _type: Any) -> _FakeBackendService:
            return backend_service

        def get_service(self, _type: Any) -> _FakeBackendService | None:
            return backend_service

    return _Provider()


@pytest.mark.asyncio
async def test_quality_verifier_integration_non_streaming_correction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force Angel to run on this single-turn request.
    config = AppConfig(
        session=SessionConfig(
            quality_verifier_model="fake_backend:guardian", quality_verifier_frequency=1
        )
    )

    def _response_factory() -> ResponseEnvelope:
        return ResponseEnvelope(content={"content": "initial output"})

    response_processor = _make_response_processor(config)
    backend_service = _FakeBackendService(corrected_text="Corrected response")
    mock_provider = _make_mock_provider(backend_service)

    # Patch get_service_provider for ResponseProcessor._apply_quality_verifier_verification
    # The function is imported from src.core.di.services at call time
    monkeypatch.setattr(
        "src.core.di.services.get_service_provider",
        lambda: mock_provider,
    )

    from tests.helpers.backend_request_manager_fixtures import (
        create_backend_request_manager,
    )

    manager = create_backend_request_manager(
        backend_processor=cast(
            IBackendProcessor, _StubBackendProcessor(_response_factory)
        ),
        response_processor=response_processor,
        mock_provider=mock_provider,
    )

    original_request = ChatRequest(
        model="fake_backend:primary",
        messages=[ChatMessage(role="user", content="Hi")],
    )

    context = _make_context(config)

    result = await manager.process_backend_request(
        backend_request=original_request,
        session_id="session-non-stream",
        context=context,
    )

    assert isinstance(result, ResponseEnvelope)
    assert result.content == "Corrected response"
    assert [req.model for req in backend_service.requests] == [
        "fake_backend:guardian",
        "fake_backend:primary",
    ]


@pytest.mark.asyncio
async def test_quality_verifier_integration_streaming_override() -> None:
    # Force Angel to run on this single-turn request.
    config = AppConfig(
        session=SessionConfig(
            quality_verifier_model="fake_backend:guardian", quality_verifier_frequency=1
        )
    )

    async def _stream() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content="Draft", metadata={})
        yield ProcessedResponse(content=" reply", metadata={"is_done": True})

    def _response_factory() -> StreamingResponseEnvelope:
        return StreamingResponseEnvelope(content=_stream())

    response_processor = _make_response_processor(config)
    backend_service = _FakeBackendService(
        corrected_text="unused",
        steering_message="Check your math",
        override=True,
    )
    mock_provider = _make_mock_provider(backend_service)

    from tests.helpers.backend_request_manager_fixtures import (
        create_backend_request_manager,
    )

    manager = create_backend_request_manager(
        backend_processor=cast(
            IBackendProcessor, _StubBackendProcessor(_response_factory)
        ),
        response_processor=response_processor,
        mock_provider=mock_provider,
    )

    original_request = ChatRequest(
        model="fake_backend:primary",
        messages=[ChatMessage(role="user", content="Hi")],
        stream=True,
    )

    context = _make_context(config)

    stream_envelope = await manager.process_backend_request(
        backend_request=original_request,
        session_id="session-stream",
        context=context,
    )

    assert isinstance(stream_envelope, StreamingResponseEnvelope)
    assert stream_envelope.content is not None

    gathered: list[str] = []
    async for chunk in stream_envelope.content:
        gathered.append(str(chunk.content))

    assert gathered == ["Draft reply"]
    assert [req.model for req in backend_service.requests] == [
        "fake_backend:guardian",
        "fake_backend:primary",
    ]
