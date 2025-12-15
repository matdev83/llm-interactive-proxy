from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_service import BackendService


class _OkBackend:
    backend_type = "openai"
    has_static_credentials = True

    def get_available_models(self) -> list[str]:
        return ["gpt-4"]

    def is_backend_functional(self) -> bool:
        return True

    async def chat_completions(
        self,
        *,
        request_data: ChatRequest,
        processed_messages: list,
        effective_model: str,
        identity: Any | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope:
        return ResponseEnvelope(content={"model": effective_model}, headers={})


class _StreamingOkBackend(_OkBackend):
    async def chat_completions(
        self,
        *,
        request_data: ChatRequest,
        processed_messages: list,
        effective_model: str,
        identity: Any | None = None,
        **kwargs: Any,
    ) -> StreamingResponseEnvelope:

        async def _gen() -> AsyncIterator[bytes]:
            yield b"data: hello\n\n"
            yield b"data: [DONE]\n\n"

        return StreamingResponseEnvelope(content=_gen())


@pytest.mark.asyncio
async def test_call_completion_updates_planning_counters_non_streaming() -> None:
    planning_phase_manager = AsyncMock()
    planning_phase_manager.apply_if_needed = AsyncMock()
    planning_phase_manager.update_counters = AsyncMock()
    planning_phase_manager.count_file_writes = Mock(return_value=0)

    session_service = AsyncMock(spec=ISessionService)
    session_service.get_session = AsyncMock(return_value=None)

    service = BackendService(
        factory=Mock(spec=BackendFactory),
        rate_limiter=Mock(),
        config=AppConfig(),
        session_service=session_service,
        app_state=Mock(spec=IApplicationState),
        planning_phase_manager=planning_phase_manager,
    )

    service._resolve_backend_and_model = AsyncMock(return_value=("openai", "gpt-4", {}))
    service._backend_lifecycle_manager.get_or_create = AsyncMock(
        return_value=_OkBackend()
    )

    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="hi")],
        extra_body={"session_id": "sess-1"},
    )

    result = await service.call_completion(request, stream=False, context=None)

    assert isinstance(result, ResponseEnvelope)
    planning_phase_manager.update_counters.assert_awaited()
    planning_phase_manager.update_counters.assert_awaited_once()
    assert planning_phase_manager.update_counters.await_args.args[0] == "sess-1"


@pytest.mark.asyncio
async def test_call_completion_updates_planning_counters_streaming_after_consume() -> (
    None
):
    planning_phase_manager = AsyncMock()
    planning_phase_manager.apply_if_needed = AsyncMock()
    planning_phase_manager.update_counters = AsyncMock()
    planning_phase_manager.count_file_writes = Mock(return_value=0)

    session_service = AsyncMock(spec=ISessionService)
    session_service.get_session = AsyncMock(return_value=None)

    service = BackendService(
        factory=Mock(spec=BackendFactory),
        rate_limiter=Mock(),
        config=AppConfig(),
        session_service=session_service,
        app_state=Mock(spec=IApplicationState),
        planning_phase_manager=planning_phase_manager,
    )

    service._resolve_backend_and_model = AsyncMock(return_value=("openai", "gpt-4", {}))
    service._backend_lifecycle_manager.get_or_create = AsyncMock(
        return_value=_StreamingOkBackend()
    )

    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="hi")],
        extra_body={"session_id": "sess-1"},
    )

    result = await service.call_completion(request, stream=True, context=None)
    assert isinstance(result, StreamingResponseEnvelope)

    planning_phase_manager.update_counters.assert_not_awaited()
    async for _ in result.content:
        pass

    planning_phase_manager.update_counters.assert_awaited_once()
    assert planning_phase_manager.update_counters.await_args.args[0] == "sess-1"
