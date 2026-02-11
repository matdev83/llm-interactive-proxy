from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.backend_request_manager.quality_verifier_stream_verifier import (
    QualityVerifierStreamVerifier,
)
from src.core.services.quality_verifier_service import QualityVerifierService


class DummyQualityVerifierFactory:
    def __init__(self, service: QualityVerifierService) -> None:
        self._service = service

    def create(self, *args: Any, **kwargs: Any) -> QualityVerifierService:
        return self._service


class DummyProvider:
    def __init__(self, backend_service: Any) -> None:
        self._backend_service = backend_service

    def get_required_service(self, _service_type: type[Any]) -> Any:
        return self._backend_service

    def get_service(self, _service_type: type[Any]) -> None:
        return None


async def _single_chunk_stream(content: str) -> AsyncIterator[ProcessedResponse]:
    yield ProcessedResponse(content=content, metadata={"is_done": True})


@pytest.mark.asyncio
async def test_stream_verifier_retries_once_on_invalid_format_then_steers() -> None:
    quality_verifier_service = QualityVerifierService("openai:gpt-4o-mini")

    class DummyBackendService:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        async def chat_completions(self, request, *args, **kwargs):
            self.requests.append(request)
            call_index = len(self.requests)

            if call_index == 1:
                return type("R", (), {"content": "not xml"})()

            if call_index == 2:
                assert request.messages[-2].role == "assistant"
                assert request.messages[-2].content == "not xml"
                assert request.messages[-1].role == "user"
                assert "FORMAT CORRECTION" in str(request.messages[-1].content)
                return type(
                    "R",
                    (),
                    {
                        "content": "<quality_verifier_decision>Steer</quality_verifier_decision>"
                        "<quality_verifier_steering_message>Fix result</quality_verifier_steering_message>"
                    },
                )()

            return type("R", (), {"content": "Corrected by Angel"})()

    backend_service = DummyBackendService()
    verifier = QualityVerifierStreamVerifier(
        quality_verifier_service_factory=DummyQualityVerifierFactory(quality_verifier_service),
        provider=cast(Any, DummyProvider(backend_service)),
    )

    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="question")],
    )
    context: dict[str, Any] = {
        "quality_verifier_model_spec": "openai:gpt-4o-mini",
        "quality_verifier_frequency": 1,
    }

    result_chunks = [
        chunk
        async for chunk in verifier.verify_or_passthrough(
            request,
            _single_chunk_stream("draft output"),
            context,
            request_context=None,
        )
    ]

    assert len(result_chunks) == 1
    assert result_chunks[0].content == "Corrected by Angel"
    assert result_chunks[0].metadata.get("corrected_by_quality_verifier") is True
    assert len(backend_service.requests) == 3


@pytest.mark.asyncio
async def test_stream_verifier_fails_open_after_second_invalid_format() -> None:
    quality_verifier_service = QualityVerifierService("openai:gpt-4o-mini")

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
    verifier = QualityVerifierStreamVerifier(
        quality_verifier_service_factory=DummyQualityVerifierFactory(quality_verifier_service),
        provider=cast(Any, DummyProvider(backend_service)),
    )

    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="question")],
    )
    context: dict[str, Any] = {
        "quality_verifier_model_spec": "openai:gpt-4o-mini",
        "quality_verifier_frequency": 1,
    }

    result_chunks = [
        chunk
        async for chunk in verifier.verify_or_passthrough(
            request,
            _single_chunk_stream("draft output"),
            context,
            request_context=None,
        )
    ]

    assert len(result_chunks) == 1
    assert result_chunks[0].content == "draft output"
    assert len(backend_service.requests) == 2


@pytest.mark.asyncio
async def test_stream_verifier_treats_backend_error_response_as_failure() -> None:
    quality_verifier_service = QualityVerifierService("openai:gpt-4o-mini")

    class DummyBackendService:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        async def chat_completions(self, request, *args, **kwargs):
            self.requests.append(request)
            return ResponseEnvelope(
                content={
                    "error": {
                        "message": "No capacity available",
                        "type": "backend_error",
                    }
                },
                status_code=503,
            )

    backend_service = DummyBackendService()
    verifier = QualityVerifierStreamVerifier(
        quality_verifier_service_factory=DummyQualityVerifierFactory(quality_verifier_service),
        provider=cast(Any, DummyProvider(backend_service)),
    )

    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="question")],
    )
    context: dict[str, Any] = {
        "quality_verifier_model_spec": "openai:gpt-4o-mini",
        "quality_verifier_frequency": 1,
    }

    result_chunks = [
        chunk
        async for chunk in verifier.verify_or_passthrough(
            request,
            _single_chunk_stream("draft output"),
            context,
            request_context=None,
        )
    ]

    assert len(result_chunks) == 1
    assert result_chunks[0].content == "draft output"
    assert len(backend_service.requests) == 1


@pytest.mark.asyncio
async def test_stream_verifier_ttft_timeout_fails_open() -> None:
    quality_verifier_service = QualityVerifierService("openai:gpt-4o-mini")

    class DummyBackendService:
        async def chat_completions(self, request, *args, **kwargs):
            async def _stream() -> AsyncIterator[ProcessedResponse]:
                yield ProcessedResponse(content="", metadata={"_keepalive": True})
                await asyncio.sleep(0.05)
                yield ProcessedResponse(content="late token", metadata={})

            return StreamingResponseEnvelope(content=_stream())

    verifier = QualityVerifierStreamVerifier(
        quality_verifier_service_factory=DummyQualityVerifierFactory(quality_verifier_service),
        provider=cast(Any, DummyProvider(DummyBackendService())),
    )

    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="question")],
    )
    context: dict[str, Any] = {
        "quality_verifier_model_spec": "openai:gpt-4o-mini",
        "quality_verifier_frequency": 1,
        "quality_verifier_ttft_timeout_seconds": 0.01,
    }

    result_chunks = [
        chunk
        async for chunk in verifier.verify_or_passthrough(
            request,
            _single_chunk_stream("draft output"),
            context,
            request_context=None,
        )
    ]

    assert len(result_chunks) == 1
    assert result_chunks[0].content == "draft output"
