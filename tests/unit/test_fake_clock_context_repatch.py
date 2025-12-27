from __future__ import annotations

import time

import pytest

from tests.utils.fake_clock import FakeClockContext


@pytest.mark.asyncio
async def test_fake_clock_context_reinstalls_time_wrapper(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """
    If another test overwrites `time.time`, FakeClockContext should re-install its
    wrapper on next use (so `clock.advance()` affects `time.time()` again).
    """

    async with FakeClockContext() as clock:
        t1 = time.time()
        clock.advance(0.5)
        t2 = time.time()
        assert (t2 - t1) == pytest.approx(0.5)

    monkeypatch.setattr(time, "time", lambda: 123.0)

    async with FakeClockContext() as clock:
        t1 = time.time()
        clock.advance(0.5)
        t2 = time.time()
        assert (t2 - t1) == pytest.approx(0.5)
