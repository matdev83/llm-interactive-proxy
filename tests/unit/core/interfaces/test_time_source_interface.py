"""Tests for ITimeSource interface contract."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from src.core.interfaces.time_source_interface import ITimeSource


class MockTimeSource(ITimeSource):
    """Mock implementation for testing interface contract."""

    def __init__(self) -> None:
        """Initialize mock time source."""
        self._utc_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        self._local_time = datetime(2024, 1, 1, 12, 0, 0)
        self._unix_time = 1704110400.0
        self._monotonic_time = 1000.0
        self._sleep_calls: list[float] = []

    def now_utc(self) -> datetime:
        """Get mock UTC time."""
        return self._utc_time

    def now_local(self) -> datetime:
        """Get mock local time."""
        return self._local_time

    def unix_time_s(self) -> float:
        """Get mock Unix time."""
        return self._unix_time

    def monotonic_s(self) -> float:
        """Get mock monotonic time."""
        return self._monotonic_time

    async def sleep(self, seconds: float) -> None:
        """Record sleep call."""
        self._sleep_calls.append(seconds)
        await asyncio.sleep(0)  # Yield control but don't actually sleep


class TestITimeSourceContract:
    """Test ITimeSource interface contract compliance."""

    def test_now_utc_returns_datetime_with_timezone(self) -> None:
        """Test that now_utc returns datetime with timezone info."""
        source = MockTimeSource()
        result = source.now_utc()
        assert isinstance(result, datetime)
        assert result.tzinfo is not None

    def test_now_local_returns_datetime(self) -> None:
        """Test that now_local returns datetime."""
        source = MockTimeSource()
        result = source.now_local()
        assert isinstance(result, datetime)

    def test_unix_time_s_returns_float(self) -> None:
        """Test that unix_time_s returns float."""
        source = MockTimeSource()
        result = source.unix_time_s()
        assert isinstance(result, float)
        assert result >= 0

    def test_monotonic_s_returns_float(self) -> None:
        """Test that monotonic_s returns float."""
        source = MockTimeSource()
        result = source.monotonic_s()
        assert isinstance(result, float)
        assert result >= 0

    @pytest.mark.asyncio
    async def test_sleep_is_async(self) -> None:
        """Test that sleep is an async method."""
        source = MockTimeSource()
        await source.sleep(1.0)
        assert len(source._sleep_calls) == 1
        assert source._sleep_calls[0] == 1.0

    def test_interface_cannot_be_instantiated(self) -> None:
        """Test that ITimeSource cannot be instantiated directly."""
        with pytest.raises(TypeError):
            ITimeSource()  # type: ignore[misc]
