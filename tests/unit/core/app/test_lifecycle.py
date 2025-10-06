from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

import pytest
from fastapi import FastAPI

from src.core.app.lifecycle import AppLifecycle
from src.core.interfaces.session_service_interface import ISessionService


class _FakeTask:
    def __init__(self, name: str = "task") -> None:
        self._name = name
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def done(self) -> bool:
        return self.cancelled

    def get_name(self) -> str:
        return self._name

    def __await__(self):  # type: ignore[override]
        async def _inner() -> None:
            if self.cancelled:
                raise asyncio.CancelledError()

        return _inner().__await__()


def test_start_background_tasks_creates_cleanup_task(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    config = {
        "session_cleanup_enabled": True,
        "session_cleanup_interval": 5,
        "session_max_age": 10,
    }
    lifecycle = AppLifecycle(app, config)

    created: dict[str, object] = {}

    def fake_create_task(
        coro: Coroutine[Any, Any, Any], name: str
    ) -> _FakeTask:
        created["coro"] = coro
        created["name"] = name
        return _FakeTask(name)

    monkeypatch.setattr(asyncio, "create_task", fake_create_task)

    lifecycle._start_background_tasks()

    assert created["name"] == "session_cleanup"
    assert lifecycle._background_tasks


@pytest.mark.asyncio
async def test_shutdown_cancels_background_tasks(caplog: pytest.LogCaptureFixture) -> None:
    app = FastAPI()
    lifecycle = AppLifecycle(app, {})
    task = _FakeTask("cleanup")
    lifecycle._background_tasks.append(task)

    caplog.set_level(logging.INFO, logger="src.core.app.lifecycle")

    await lifecycle.shutdown()

    assert task.cancelled
    assert "Cancelled background task: cleanup" in caplog.text


class _DummyProvider:
    def __init__(self, service: ISessionService | None) -> None:
        self._service = service

    def get_service(self, interface):  # type: ignore[no-untyped-def]
        return self._service


class _DummySessionService:
    def __init__(self) -> None:
        self.calls: list[int] = []

    async def cleanup_expired_sessions(self, max_age: int) -> int:
        self.calls.append(max_age)
        return 3


@pytest.mark.asyncio
async def test_session_cleanup_task_invokes_service(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    app = FastAPI()
    lifecycle = AppLifecycle(app, {})
    service = _DummySessionService()
    app.state.service_provider = _DummyProvider(service)

    call_count = 0

    async def fake_sleep(interval: int) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    caplog.set_level(logging.INFO, logger="src.core.app.lifecycle")

    with pytest.raises(asyncio.CancelledError):
        await lifecycle._session_cleanup_task(interval=1, max_age=7)

    assert service.calls == [7]
    assert "Cleaned up 3 expired sessions" in caplog.text


@pytest.mark.asyncio
async def test_session_cleanup_task_warns_when_provider_missing(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    app = FastAPI()
    lifecycle = AppLifecycle(app, {})
    app.state.service_provider = None

    call_count = 0

    async def fake_sleep(interval: int) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    caplog.set_level(logging.WARNING, logger="src.core.app.lifecycle")

    with pytest.raises(asyncio.CancelledError):
        await lifecycle._session_cleanup_task(interval=1, max_age=7)

    assert "Service provider not available for session cleanup" in caplog.text
