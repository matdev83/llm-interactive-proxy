from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic.types import JsonValue
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.backend_processor import BackendProcessor

from tests.helpers.backend_request_manager_fixtures import (
    create_backend_request_manager,
)


class _RecordingBackendService:
    def __init__(self) -> None:
        self.categories: list[str] = []

    @staticmethod
    def _classify(context: RequestContext | None) -> str:
        extensions = getattr(context, "extensions", None)
        if isinstance(extensions, dict):
            if bool(extensions.get("auxiliary_request")):
                return "auxiliary_sidecar_inference"
            if bool(extensions.get("model_replacement_active")):
                return "random_model_replacement"
            if bool(extensions.get("quality_verifier_model")):
                return "quality_verifier_verification"
        return "primary_request_execution"

    async def call_completion(
        self,
        request: ChatRequest,
        stream: bool = False,
        allow_failover: bool = True,
        context: RequestContext | None = None,
    ) -> ResponseEnvelope:
        _ = stream
        _ = allow_failover
        _ = request
        category = self._classify(context)
        self.categories.append(category)
        if category == "quality_verifier_verification":
            return ResponseEnvelope(
                content="<quality_verifier_decision>Pass</quality_verifier_decision>",
                status_code=200,
                headers={},
            )
        return ResponseEnvelope(
            content={
                "id": "chatcmpl-runtime-contract",
                "object": "chat.completion",
                "created": 0,
                "model": "openai/gpt-4o",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
            },
            status_code=200,
            headers={},
        )

    async def chat_completions(
        self,
        request: ChatRequest,
        **kwargs,
    ) -> ResponseEnvelope:
        return await self.call_completion(
            request=request,
            stream=bool(kwargs.get("stream", False)),
            allow_failover=bool(kwargs.get("allow_failover", True)),
            context=kwargs.get("context"),
        )


def _build_context(
    *, session_id: str, extensions: dict[str, JsonValue] | None
) -> RequestContext:
    return RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        session_id=session_id,
        extensions=extensions or {},
    )


@pytest.mark.asyncio
async def test_runtime_categories_use_shared_backend_service_entrypoint() -> None:
    backend_service = _RecordingBackendService()
    session_service = MagicMock()
    session_service.get_session = AsyncMock(return_value=None)
    processor = BackendProcessor(
        backend_service=cast(IBackendService, backend_service),
        session_service=session_service,
    )

    request = ChatRequest(
        model="openai/gpt-4o",
        messages=[ChatMessage(role="user", content="hello")],
    )

    await processor.process_backend_request(
        request=request,
        session_id="sess-regular",
        context=_build_context(session_id="sess-regular", extensions={}),
    )
    await processor.process_backend_request(
        request=request.model_copy(update={"model": "openai/gpt-4o-mini"}),
        session_id="sess-rmr",
        context=_build_context(
            session_id="sess-rmr",
            extensions={"model_replacement_active": True},
        ),
    )
    await processor.process_backend_request(
        request=request.model_copy(update={"model": "openai/gpt-4o-mini"}),
        session_id="sess-aux",
        context=_build_context(
            session_id="sess-aux",
            extensions={
                "auxiliary_request": True,
                "auxiliary_effective_session_id": "aux-1-abcdef",
            },
        ),
    )

    assert backend_service.categories == [
        "primary_request_execution",
        "random_model_replacement",
        "auxiliary_sidecar_inference",
    ]


def _build_stream(
    chunks: list[ProcessedResponse],
) -> AsyncIterator[ProcessedResponse]:
    async def _iterator() -> AsyncIterator[ProcessedResponse]:
        for chunk in chunks:
            yield chunk

    return _iterator()


@pytest.mark.asyncio
async def test_quality_verifier_flow_uses_shared_backend_service_entrypoint() -> None:
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    response_processor.process_streaming_response = (
        lambda stream, _session_id, context=None, **kwargs: stream
    )
    backend_service = _RecordingBackendService()

    class _Provider:
        def get_required_service(self, _service_type):  # type: ignore[no-untyped-def]
            return backend_service

    manager = create_backend_request_manager(
        backend_processor=backend_processor,
        response_processor=response_processor,
        mock_provider=_Provider(),
    )

    original_request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="verify me")],
        stream=True,
    )
    backend_processor.process_backend_request.return_value = StreamingResponseEnvelope(
        content=_build_stream(
            [
                ProcessedResponse(content="chunk-1", metadata={}),
                ProcessedResponse(content="chunk-2", metadata={"is_done": True}),
            ]
        )
    )

    context = _build_context(
        session_id="sess-qv",
        extensions={
            "quality_verifier_model": "openai:gpt-4o-mini",
            "quality_verifier_frequency": 1,
        },
    )
    context.original_request = original_request

    result = await manager.process_backend_request(original_request, "sess-qv", context)
    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    async for _ in result.content:
        pass

    assert "quality_verifier_verification" in backend_service.categories
