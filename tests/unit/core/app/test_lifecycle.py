import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI

from src.core.app.lifecycle import AppLifecycle


class _DummyTask:
    def __init__(self, name: str | None = None) -> None:
        self._name = name or "task"
        self.cancel_called = False

    def cancel(self) -> None:
        self.cancel_called = True

    def done(self) -> bool:
        return False

    def get_name(self) -> str:
        return self._name

    def __await__(self):  # type: ignore[override]
        async def _dummy() -> None:
            return None

        return _dummy().__await__()


class _SequenceProvider:
    def __init__(self, availability: list[bool], services: list[Any]) -> None:
        self._availability = availability
        self._services = services
        self._availability_index = 0
        self._service_index = 0

    def __bool__(self) -> bool:
        if self._availability_index < len(self._availability):
            result = self._availability[self._availability_index]
            self._availability_index += 1
            return result
        return True

    def get_service(self, interface: object) -> Any:
        if self._service_index < len(self._services):
            service = self._services[self._service_index]
            self._service_index += 1
            return service
        return None


def test_startup_triggers_background_task_start(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    lifecycle = AppLifecycle(app, {"session_cleanup_enabled": False})
    start_mock = Mock()
    monkeypatch.setattr(lifecycle, "_start_background_tasks", start_mock)

    asyncio.run(lifecycle.startup())

    start_mock.assert_called_once_with()


def test_start_background_tasks_creates_session_cleanup_task(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    config = {
        "session_cleanup_enabled": True,
        "session_cleanup_interval": 5,
        "session_max_age": 10,
    }
    lifecycle = AppLifecycle(app, config)

    scheduled: dict[str, Any] = {}

    def fake_create_task(coro: Any, name: str | None = None) -> _DummyTask:
        scheduled["name"] = name
        scheduled["task"] = _DummyTask(name)
        scheduled["coro"] = coro
        return scheduled["task"]

    cleanup_mock = AsyncMock()

    monkeypatch.setattr(asyncio, "create_task", fake_create_task)
    monkeypatch.setattr(AppLifecycle, "_session_cleanup_task", cleanup_mock)

    lifecycle._start_background_tasks()

    cleanup_mock.assert_called_once_with(5, 10)
    assert scheduled["name"] == "session_cleanup"
    assert lifecycle._background_tasks == [scheduled["task"]]


def test_start_background_tasks_skips_when_cleanup_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    lifecycle = AppLifecycle(app, {"session_cleanup_enabled": False})

    def fail_create_task(*_: Any, **__: Any) -> None:
        raise AssertionError("create_task should not be called when cleanup is disabled")

    monkeypatch.setattr(asyncio, "create_task", fail_create_task)

    lifecycle._start_background_tasks()

    assert lifecycle._background_tasks == []


def test_shutdown_waits_for_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    lifecycle = AppLifecycle(app, {})

    stop_mock = AsyncMock()
    close_mock = AsyncMock()

    monkeypatch.setattr(lifecycle, "_stop_background_tasks", stop_mock)
    monkeypatch.setattr(lifecycle, "_close_connections", close_mock)

    asyncio.run(lifecycle.shutdown())

    stop_mock.assert_awaited_once_with()
    close_mock.assert_awaited_once_with()


def test_stop_background_tasks_cancels_pending_tasks() -> None:
    app = FastAPI()
    lifecycle = AppLifecycle(app, {})

    pending_task = _DummyTask("pending")
    done_task = _DummyTask("done")

    def done_true() -> bool:
        return True

    local_patch = pytest.MonkeyPatch()
    local_patch.setattr(done_task, "done", done_true)

    lifecycle._background_tasks.extend([pending_task, done_task])

    asyncio.run(lifecycle._stop_background_tasks())

    assert pending_task.cancel_called is True
    assert done_task.cancel_called is False
    assert lifecycle._background_tasks == [pending_task, done_task]

    local_patch.undo()


def test_session_cleanup_task_handles_provider_and_service_states(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    app = FastAPI()
    lifecycle = AppLifecycle(app, {})

    caplog.set_level(logging.INFO)

    class SessionService:
        def __init__(self) -> None:
            self.calls: list[int] = []

        async def cleanup_expired_sessions(self, max_age: int) -> int:
            self.calls.append(max_age)
            return 3

    service = SessionService()
    provider = _SequenceProvider([False, True, True], [None, service])
    app.state.service_provider = provider

    original_sleep = asyncio.sleep
    sleep_calls = 0

    async def fake_sleep(delay: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 4:
            raise asyncio.CancelledError
        await original_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    async def runner() -> None:
        task = asyncio.create_task(lifecycle._session_cleanup_task(0, 99))
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(runner())

    assert service.calls == [99]
    assert sleep_calls == 4
