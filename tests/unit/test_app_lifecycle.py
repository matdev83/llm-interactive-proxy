import asyncio
import logging
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from src.core.app.lifecycle import AppLifecycle


class DummySessionService:
    def __init__(self) -> None:
        self.calls: list[int] = []

    async def cleanup_expired_sessions(self, max_age: int) -> int:
        self.calls.append(max_age)
        return 3


class DummyProvider:
    def __init__(self, service: object | None) -> None:
        self._service = service

    def get_service(self, service_type: type) -> object | None:  # pragma: no cover - signature compatibility
        return self._service


@pytest.mark.asyncio
async def test_startup_triggers_background_task_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    lifecycle = AppLifecycle(app, {})

    called: list[bool] = []

    def fake_start() -> None:
        called.append(True)

    monkeypatch.setattr(lifecycle, "_start_background_tasks", fake_start)

    await lifecycle.startup()

    assert called == [True]


@pytest.mark.asyncio
async def test_shutdown_stops_tasks_and_closes_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    lifecycle = AppLifecycle(app, {})

    stop_called: list[bool] = []
    close_called: list[bool] = []

    async def fake_stop() -> None:
        stop_called.append(True)

    async def fake_close() -> None:
        close_called.append(True)

    monkeypatch.setattr(lifecycle, "_stop_background_tasks", fake_stop)
    monkeypatch.setattr(lifecycle, "_close_connections", fake_close)

    await lifecycle.shutdown()

    assert stop_called == [True]
    assert close_called == [True]


def test_start_background_tasks_creates_cleanup_task(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    config = {
        "session_cleanup_enabled": True,
        "session_cleanup_interval": 5,
        "session_max_age": 10,
    }
    lifecycle = AppLifecycle(app, config)

    created: dict[str, object] = {}

    def fake_create_task(coro: object, name: str | None = None) -> SimpleNamespace:
        created["coro"] = coro
        created["name"] = name
        return SimpleNamespace(get_name=lambda: name, done=lambda: True)

    monkeypatch.setattr(asyncio, "create_task", fake_create_task)

    lifecycle._start_background_tasks()

    assert created["name"] == "session_cleanup"
    assert lifecycle._background_tasks


@pytest.mark.asyncio
async def test_stop_background_tasks_cancels_running_tasks() -> None:
    app = FastAPI()
    lifecycle = AppLifecycle(app, {})

    class DummyTask:
        def __init__(self) -> None:
            self.cancel_called = False

        def done(self) -> bool:
            return False

        def cancel(self) -> None:
            self.cancel_called = True

        def get_name(self) -> str:
            return "dummy"

        def __await__(self):  # pragma: no cover - tiny shim delegating to coroutine
            async def _inner() -> None:
                raise asyncio.CancelledError

            return _inner().__await__()

    task = DummyTask()
    lifecycle._background_tasks = [task]

    await lifecycle._stop_background_tasks()

    assert task.cancel_called is True


@pytest.mark.asyncio
async def test_session_cleanup_task_invokes_session_service(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    service = DummySessionService()
    app.state.service_provider = DummyProvider(service)
    lifecycle = AppLifecycle(app, {})

    original_sleep = asyncio.sleep
    sleep_calls = {"count": 0}

    async def fake_sleep(interval: float) -> None:
        sleep_calls["count"] += 1
        if interval == 0:
            await original_sleep(0)
            return
        if sleep_calls["count"] == 1:
            return
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    task = asyncio.create_task(lifecycle._session_cleanup_task(1, 42))

    await original_sleep(0)

    assert service.calls == [42]

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_session_cleanup_task_logs_when_provider_missing(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    app = FastAPI()
    app.state.service_provider = None
    lifecycle = AppLifecycle(app, {})

    original_sleep = asyncio.sleep

    async def fake_sleep(interval: float) -> None:
        if interval == 0:
            await original_sleep(0)
            return
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with caplog.at_level(logging.WARNING):
        task = asyncio.create_task(lifecycle._session_cleanup_task(1, 10))
        await original_sleep(0)
        with pytest.raises(asyncio.CancelledError):
            await task

    assert "Service provider not available" in caplog.text
