from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.app.controllers.session_resolution import resolve_session_before_capture
from src.core.domain.request_context import RequestContext


def _build_context(*, session_id: str | None = None) -> RequestContext:
    return RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=MagicMock(),
        request_id="req-session-resolution",
        session_id=session_id,
    )


@pytest.mark.asyncio
async def test_resolve_session_before_capture_uses_session_manager_when_available() -> (
    None
):
    context = _build_context()
    expected_session_id = "llm-b2bua-123e4567-e89b-12d3-a456-426614174000"

    session_manager = MagicMock()
    session_manager.resolve_session_id = AsyncMock(return_value=expected_session_id)
    service_provider = MagicMock()
    service_provider.get_service.return_value = session_manager

    resolved = await resolve_session_before_capture(
        service_provider=service_provider,
        context=context,
    )

    assert resolved == expected_session_id
    assert context.session_id == expected_session_id
    session_manager.resolve_session_id.assert_awaited_once_with(context)


@pytest.mark.asyncio
async def test_resolve_session_before_capture_fails_open_without_provider() -> None:
    context = _build_context(session_id="legacy-session")

    resolved = await resolve_session_before_capture(
        service_provider=None,
        context=context,
    )

    assert resolved == "legacy-session"
    assert context.session_id == "legacy-session"


@pytest.mark.asyncio
async def test_resolve_session_before_capture_fails_open_when_provider_lookup_fails() -> (
    None
):
    context = _build_context(session_id="legacy-session")

    service_provider = MagicMock()
    service_provider.get_service.side_effect = RuntimeError("lookup failed")

    resolved = await resolve_session_before_capture(
        service_provider=service_provider,
        context=context,
    )

    assert resolved == "legacy-session"
    assert context.session_id == "legacy-session"


@pytest.mark.asyncio
async def test_resolve_session_before_capture_fails_open_when_resolution_fails() -> (
    None
):
    context = _build_context(session_id="legacy-session")

    session_manager = MagicMock()
    session_manager.resolve_session_id = AsyncMock(side_effect=RuntimeError("boom"))
    service_provider = MagicMock()
    service_provider.get_service.return_value = session_manager

    resolved = await resolve_session_before_capture(
        service_provider=service_provider,
        context=context,
    )

    assert resolved == "legacy-session"
    assert context.session_id == "legacy-session"
