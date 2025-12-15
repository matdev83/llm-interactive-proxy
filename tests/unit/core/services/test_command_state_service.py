from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from src.core.domain.session import Session
from src.core.services.command_state_service import CommandStateService


@pytest.mark.asyncio
async def test_get_session_delegates_to_session_service() -> None:
    session_service = AsyncMock()
    expected = Session(session_id="session-123")
    session_service.get_session.return_value = expected

    service = CommandStateService(session_service=session_service)
    result = await service.get_session("session-123")

    session_service.get_session.assert_awaited_once_with("session-123")
    assert result is expected


@pytest.mark.asyncio
async def test_update_session_delegates_to_session_service() -> None:
    session_service = AsyncMock()
    service = CommandStateService(session_service=session_service)
    session = Session(session_id="session-456")

    await service.update_session(session)

    session_service.update_session.assert_awaited_once_with(session)


def test_build_adapter_returns_new_instance() -> None:
    session_service = AsyncMock()
    service = CommandStateService(session_service=session_service)
    session = Session(session_id="session-789")

    adapter_one = service.build_session_adapter(session)
    adapter_two = service.build_session_adapter(session)

    assert adapter_one is not adapter_two
    assert adapter_one.get_command_prefix() is None
