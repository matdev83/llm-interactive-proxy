from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI

from src.core.app.lifecycle import AppLifecycle


class DummySessionService:
    def __init__(self) -> None:
        self.cleanup_calls: list[int] = []

    async def cleanup_expired_sessions(self, max_age: int) -> int:
        self.cleanup_calls.append(max_age)
        await asyncio.sleep(0)
        return 2


class DummyProvider:
    def __init__(self, service: DummySessionService | None) -> None:
        self._service = service
        self.requests: list[type[object]] = []

    def get_service(self, service_type: type[object]) -> DummySessionService | None:
        self.requests.append(service_type)
        return self._service


@pytest.mark.asyncio
async def test_startup_and_shutdown_manage_cleanup_tasks() -> None:
    app = FastAPI()
    service = DummySessionService()
    provider = DummyProvider(service)
    app.state.service_provider = provider

    lifecycle = AppLifecycle(
        app,
        {
            "session_cleanup_enabled": True,
            "session_cleanup_interval": 0,
            "session_max_age": 120,
        },
    )

    await lifecycle.startup()

    assert len(lifecycle._background_tasks) == 1
    task = lifecycle._background_tasks[0]
    assert task.get_name() == "session_cleanup"

    await lifecycle.shutdown()

    assert task.cancelled()


@pytest.mark.asyncio
async def test_session_cleanup_task_invokes_cleanup_when_available() -> None:
    app = FastAPI()
    service = DummySessionService()
    provider = DummyProvider(service)
    app.state.service_provider = provider

    lifecycle = AppLifecycle(app, {})

    task = asyncio.create_task(lifecycle._session_cleanup_task(0, 42))
    try:
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert service.cleanup_calls == [42]
        assert provider.requests
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_session_cleanup_task_skips_when_provider_missing() -> None:
    app = FastAPI()
    app.state.service_provider = None

    lifecycle = AppLifecycle(app, {})

    task = asyncio.create_task(lifecycle._session_cleanup_task(0, 55))
    service = DummySessionService()
    try:
        await asyncio.sleep(0)

        app.state.service_provider = DummyProvider(service)

        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert service.cleanup_calls == [55]
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
