from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from src.core.app.lifecycle import AppLifecycle


@pytest.mark.asyncio
async def test_startup_and_shutdown_manage_background_tasks() -> None:
    app = FastAPI()
    app.state.service_provider = None

    lifecycle = AppLifecycle(
        app,
        {
            "session_cleanup_enabled": True,
            "session_cleanup_interval": 0,
            "session_max_age": 1,
        },
    )

    await lifecycle.startup()

    assert len(lifecycle._background_tasks) == 1  # noqa: SLF001
    task = lifecycle._background_tasks[0]  # noqa: SLF001
    assert task.get_name() == "session_cleanup"
    assert not task.done()

    await asyncio.sleep(0)
    await lifecycle.shutdown()

    assert task.cancelled()


@pytest.mark.asyncio
async def test_session_cleanup_task_invokes_service() -> None:
    app = FastAPI()
    call_event = asyncio.Event()

    async def cleanup_expired_sessions(max_age: int) -> int:
        call_event.set()
        return max_age

    session_service = SimpleNamespace(
        cleanup_expired_sessions=AsyncMock(side_effect=cleanup_expired_sessions)
    )

    class Provider:
        def __init__(self, service: object) -> None:
            self._service = service

        def get_service(self, service_type: object) -> object:
            return self._service

    app.state.service_provider = Provider(session_service)

    lifecycle = AppLifecycle(app, {})

    task = asyncio.create_task(lifecycle._session_cleanup_task(0, 42))  # noqa: SLF001

    await asyncio.wait_for(call_event.wait(), timeout=1)
    session_service.cleanup_expired_sessions.assert_awaited_once_with(42)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
