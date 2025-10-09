from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.session import Session
from src.core.services.backend_processor import BackendProcessor


def _build_session_with_failover() -> Session:
    session = Session(session_id="test-session")
    backend_config = session.state.backend_config.with_failover_route("route1", "k")
    backend_config = backend_config.with_appended_route_element(
        "route1", "openai:gpt-4"
    )
    session.state = session.state.with_backend_config(backend_config)
    return session


@pytest.mark.asyncio
async def test_backend_processor_prefers_session_failover_routes() -> None:
    backend_service = AsyncMock()
    backend_service.call_completion.return_value = ResponseEnvelope(content={})

    session_service = AsyncMock()
    session = _build_session_with_failover()
    session_service.get_session.return_value = session

    app_state = MagicMock()
    app_state.get_failover_routes.return_value = [
        {"name": "global", "policy": "m", "elements": ["openai:other"]}
    ]

    processor = BackendProcessor(backend_service, session_service, app_state)

    request = ChatRequest(
        model="route1", messages=[ChatMessage(role="user", content="hi")]
    )

    await processor.process_backend_request(request, session_id="test-session")

    backend_service.call_completion.assert_awaited_once()
    called_request = backend_service.call_completion.await_args.kwargs["request"]
    assert called_request.extra_body is not None
    assert called_request.extra_body["failover_routes"] == [
        {
            "name": "route1",
            "policy": "k",
            "elements": ["openai:gpt-4"],
        }
    ]


@pytest.mark.asyncio
async def test_backend_processor_falls_back_to_app_state_routes() -> None:
    backend_service = AsyncMock()
    backend_service.call_completion.return_value = ResponseEnvelope(content={})

    session_service = AsyncMock()
    session = Session(session_id="test-session")
    session_service.get_session.return_value = session

    app_state = MagicMock()
    app_state.get_failover_routes.return_value = [
        {"name": "global", "policy": "m", "elements": ["openai:other"]}
    ]

    processor = BackendProcessor(backend_service, session_service, app_state)

    request = ChatRequest(
        model="global", messages=[ChatMessage(role="user", content="hi")]
    )

    await processor.process_backend_request(request, session_id="test-session")

    backend_service.call_completion.assert_awaited_once()
    called_request = backend_service.call_completion.await_args.kwargs["request"]
    assert called_request.extra_body is not None
    assert called_request.extra_body["failover_routes"] == [
        {
            "name": "global",
            "policy": "m",
            "elements": ["openai:other"],
        }
    ]

