from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch

import pytest
from src.connectors.hybrid import HybridConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_service import BackendService
from src.core.services.translation_service import TranslationService


class DummyTranslationService:
    """Minimal translation service used for integration testing."""

    def to_domain_request(self, data: Any, backend: str) -> CanonicalChatRequest:
        messages = data.get("messages", [])
        if not messages:
            messages = [{"role": "user", "content": ""}]
        stream = data.get("stream")
        return CanonicalChatRequest(
            model=data["model"], messages=messages, stream=stream
        )


class StubBackendService:
    """Backend service stub that simulates reasoning phase calls."""

    def __init__(
        self,
        *,
        reasoning_chunks: list[ProcessedResponse],
    ) -> None:
        self.reasoning_chunks = reasoning_chunks
        self.calls: list[tuple[str, bool]] = []

    def _stream(
        self, chunks: list[ProcessedResponse]
    ) -> AsyncIterator[ProcessedResponse]:
        async def iterator() -> AsyncIterator[ProcessedResponse]:
            for chunk in chunks:
                yield chunk

        return iterator()

    async def call_completion(
        self,
        request: CanonicalChatRequest,
        *,
        stream: bool,
        allow_failover: bool,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        self.calls.append((request.model, stream))

        if request.model == "MiniMax-M2":
            return StreamingResponseEnvelope(
                content=self._stream(self.reasoning_chunks)
            )

        raise AssertionError(f"Unexpected model request: {request.model}")


class StubExecutionConnector:
    """Connector returned by the backend factory during execution phase."""

    def __init__(
        self,
        stream_chunks: list[ProcessedResponse],
        non_stream_response: Any | None,
    ) -> None:
        self.stream_chunks = stream_chunks
        self.non_stream_response = non_stream_response
        self.calls: list[dict[str, Any]] = []

    def _stream(self) -> AsyncIterator[ProcessedResponse]:
        async def iterator() -> AsyncIterator[ProcessedResponse]:
            for chunk in self.stream_chunks:
                yield chunk

        return iterator()

    async def chat_completions(self, *args: Any, **kwargs: Any) -> Any:
        request = kwargs.get("request_data")
        if isinstance(request, dict):
            stream = bool(request.get("stream", False))
        else:
            stream = bool(getattr(request, "stream", False))
        self.calls.append({"stream": stream, "request": request})

        if stream:
            return StreamingResponseEnvelope(content=self._stream())

        return ResponseEnvelope(content=self.non_stream_response)


class StubBackendFactory:
    def __init__(
        self,
        execution_stream_chunks: list[ProcessedResponse],
        execution_response: Any | None,
    ) -> None:
        self.execution_stream_chunks = execution_stream_chunks
        self.execution_response = execution_response
        self.calls: list[str] = []

    async def ensure_backend(
        self, backend: str, config: AppConfig, backend_config: Any
    ) -> StubExecutionConnector:
        self.calls.append(backend)
        return StubExecutionConnector(
            self.execution_stream_chunks, self.execution_response
        )


def _build_hybrid_connector() -> HybridConnector:
    config = AppConfig()
    if not hasattr(config, "backends"):
        config.backends = cast(Any, SimpleNamespace(disable_hybrid_backend=False))
    else:
        config.backends.disable_hybrid_backend = False

    translation_service = cast(TranslationService, DummyTranslationService())

    connector = HybridConnector(
        client=Mock(),
        config=config,
        translation_service=translation_service,
        backend_registry=Mock(),
    )
    return connector


def _default_request(stream: bool) -> dict[str, Any]:
    return {
        "model": "hybrid:[minimax:MiniMax-M2,zai-coding-plan:glm-4.6]",
        "messages": [{"role": "user", "content": "Solve the task"}],
        "stream": stream,
    }


def _service_dispatcher(
    backend_service: StubBackendService, backend_factory: StubBackendFactory
) -> Any:
    def _dispatch(service_cls: Any) -> Any:
        if service_cls is BackendService:
            return backend_service
        if service_cls is BackendFactory:
            return backend_factory
        raise AssertionError(f"Unexpected service requested: {service_cls}")

    return _dispatch


@pytest.mark.asyncio
async def test_hybrid_streaming_exposes_reasoning_before_execution() -> None:
    reasoning_chunks = [
        ProcessedResponse(
            content={
                "id": "reason-1",
                "choices": [
                    {
                        "delta": {
                            "reasoning_content": "<think>Consider steps</think>",
                        }
                    }
                ],
            },
            metadata={"is_done": False},
        ),
        ProcessedResponse(metadata={"is_done": True}),
    ]

    execution_chunks = [
        ProcessedResponse(
            content='data: {"choices":[{"delta":{"content":"Answer"}}]}\n\n'
        ),
        ProcessedResponse(metadata={"is_done": True}),
    ]

    backend_service = StubBackendService(reasoning_chunks=reasoning_chunks)
    backend_factory = StubBackendFactory(
        execution_stream_chunks=execution_chunks,
        execution_response=None,
    )

    connector = _build_hybrid_connector()
    request_payload = _default_request(stream=True)

    with patch(
        "src.core.di.services.get_required_service",
        side_effect=_service_dispatcher(backend_service, backend_factory),
    ):
        response = await connector.chat_completions(
            request_payload,
            processed_messages=request_payload["messages"],
            effective_model=request_payload["model"],
        )

    assert isinstance(response, StreamingResponseEnvelope)
    assert response.content is not None
    chunks: list[ProcessedResponse] = [chunk async for chunk in response.content]
    assert len(chunks) >= 2

    reasoning_chunk, execution_chunk = chunks[0], chunks[1]
    assert reasoning_chunk.metadata.get("hybrid_phase") == "reasoning"
    assert isinstance(reasoning_chunk.content, str)
    assert "<think>" in reasoning_chunk.content
    assert isinstance(execution_chunk.content, str)
    assert "Answer" in execution_chunk.content

    assert backend_service.calls == [("MiniMax-M2", True)]
    assert backend_factory.calls == ["zai-coding-plan"]


@pytest.mark.asyncio
async def test_hybrid_non_streaming_merges_reasoning_into_response() -> None:
    reasoning_chunks = [
        ProcessedResponse(
            content={
                "id": "reason-1",
                "choices": [
                    {
                        "delta": {
                            "reasoning_content": "<think>Draft plan</think>",
                        }
                    }
                ],
            },
            metadata={"is_done": False},
        ),
        ProcessedResponse(metadata={"is_done": True}),
    ]

    execution_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Here is the solution.",
                }
            }
        ]
    }

    backend_service = StubBackendService(reasoning_chunks=reasoning_chunks)
    backend_factory = StubBackendFactory(
        execution_stream_chunks=[],
        execution_response=execution_response,
    )

    connector = _build_hybrid_connector()
    request_payload = _default_request(stream=False)

    with patch(
        "src.core.di.services.get_required_service",
        side_effect=_service_dispatcher(backend_service, backend_factory),
    ):
        response = await connector.chat_completions(
            request_payload,
            processed_messages=request_payload["messages"],
            effective_model=request_payload["model"],
        )

    assert isinstance(response, ResponseEnvelope)
    final_content = response.content
    assert isinstance(final_content, dict)

    message_content = final_content["choices"][0]["message"]["content"]
    assert "<think>" in message_content
    assert "Here is the solution." in message_content

    assert backend_service.calls == [("MiniMax-M2", True)]
    assert backend_factory.calls == ["zai-coding-plan"]
