from __future__ import annotations

import asyncio

import pytest
from src.core.database.config import DatabaseConfig
from src.core.database.engine import DatabaseEngine


class _FakeSession:
    def __init__(self) -> None:
        self.rollback_called = asyncio.Event()
        self.close_called = asyncio.Event()

    async def commit(self) -> None:  # pragma: no cover
        return None

    async def rollback(self) -> None:
        self.rollback_called.set()
        await asyncio.sleep(0)

    async def close(self) -> None:
        self.close_called.set()
        await asyncio.sleep(0)


class _TestEngine(DatabaseEngine):
    def __init__(self, session: _FakeSession) -> None:
        super().__init__(DatabaseConfig(url="sqlite+aiosqlite:///:memory:"))
        self._test_session = session

    @property  # type: ignore[override]
    def session_factory(self):  # type: ignore[override]
        return lambda: self._test_session


@pytest.mark.asyncio
async def test_database_engine_session_cleanup_runs_under_cancellation() -> None:
    """Ensure rollback/close complete even when the request task is cancelled."""
    fake_session = _FakeSession()
    engine = _TestEngine(fake_session)

    entered = asyncio.Event()

    async def _worker() -> None:
        async with engine.session():
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(_worker())
    await asyncio.wait_for(entered.wait(), timeout=2.0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert fake_session.rollback_called.is_set()
    assert fake_session.close_called.is_set()
