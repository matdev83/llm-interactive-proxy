"""Tests for TimeSource service implementation."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import pytest
from src.core.interfaces.time_source_interface import ITimeSource
from src.core.services.time_source_service import TimeOverride, TimeSource

from tests.unit.fixtures.markers import real_time


class TestTimeSourceDefaultBehavior:
    """Test TimeSource default behavior (no override)."""

    @real_time(
        reason="Tests that TimeSource returns real system time when no override is set"
    )
    def test_now_utc_returns_current_utc_time(self) -> None:
        """Test that now_utc returns current UTC time."""
        source = TimeSource()
        before = datetime.now(timezone.utc)
        result = source.now_utc()
        after = datetime.now(timezone.utc)

        assert isinstance(result, datetime)
        assert result.tzinfo is not None
        assert before <= result <= after

    @real_time(
        reason="Tests that TimeSource returns real system time when no override is set"
    )
    def test_now_local_returns_current_local_time(self) -> None:
        """Test that now_local returns current local time."""
        source = TimeSource()
        before = datetime.now()
        result = source.now_local()
        after = datetime.now()

        assert isinstance(result, datetime)
        assert before <= result <= after

    @real_time(
        reason="Tests that TimeSource returns real system time when no override is set"
    )
    def test_unix_time_s_returns_current_epoch_seconds(self) -> None:
        """Test that unix_time_s returns current epoch seconds."""
        source = TimeSource()
        before = time.time()
        result = source.unix_time_s()
        after = time.time()

        assert isinstance(result, float)
        assert before <= result <= after

    @real_time(
        reason="Tests that TimeSource returns real system time when no override is set"
    )
    def test_unix_time_s_consistent_with_now_utc(self) -> None:
        """Test that unix_time_s and now_utc are consistent."""
        source = TimeSource()
        unix_time = source.unix_time_s()
        utc_time = source.now_utc()

        # Convert UTC datetime to Unix timestamp
        expected_unix = utc_time.timestamp()

        # Allow small difference due to timing
        assert abs(unix_time - expected_unix) < 0.1

    @pytest.mark.asyncio
    async def test_utc_local_epoch_consistency_with_override(self) -> None:
        """Test that UTC, local, and epoch times are consistent when using TimeOverride."""
        fixed_utc = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        fixed_local = datetime(2024, 1, 1, 12, 0, 0)
        fixed_unix = 1704110400.0

        mock_source = MockTimeSource(
            utc_time=fixed_utc,
            local_time=fixed_local,
            unix_time=fixed_unix,
            monotonic_time=1000.0,
        )

        source = TimeSource()

        async with TimeOverride(mock_source):
            utc_time = source.now_utc()
            local_time = source.now_local()
            unix_time = source.unix_time_s()

            # Convert UTC datetime to Unix timestamp
            expected_unix = utc_time.timestamp()

            # Should be exactly consistent when using override
            assert unix_time == expected_unix
            assert unix_time == fixed_unix
            assert utc_time == fixed_utc
            assert local_time == fixed_local

    @pytest.mark.asyncio
    async def test_utc_epoch_relationship_consistency(self) -> None:
        """Test that now_utc() and unix_time_s() maintain consistent relationship."""
        # Test with multiple different time values to ensure consistency
        test_cases = [
            (datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc), 1577836800.0),
            (datetime(2024, 6, 15, 14, 30, 0, tzinfo=timezone.utc), 1718461800.0),
            (datetime(2030, 12, 31, 23, 59, 59, tzinfo=timezone.utc), 1924991999.0),
        ]

        for fixed_utc, expected_unix in test_cases:
            mock_source = MockTimeSource(
                utc_time=fixed_utc,
                local_time=fixed_utc.replace(tzinfo=None),
                unix_time=expected_unix,
                monotonic_time=1000.0,
            )

            source = TimeSource()

            async with TimeOverride(mock_source):
                utc_time = source.now_utc()
                unix_time = source.unix_time_s()

                # Verify exact consistency
                assert unix_time == expected_unix
                assert utc_time.timestamp() == expected_unix
                assert utc_time == fixed_utc

    @real_time(
        reason="Tests that TimeSource returns real system time when no override is set"
    )
    def test_monotonic_s_returns_monotonic_time(self) -> None:
        """Test that monotonic_s returns monotonic time."""
        source = TimeSource()
        before = time.monotonic()
        result = source.monotonic_s()
        after = time.monotonic()

        assert isinstance(result, float)
        assert before <= result <= after

    @pytest.mark.asyncio
    @real_time(reason="Tests that TimeSource.sleep delegates to real asyncio.sleep")
    async def test_sleep_delegates_to_asyncio_sleep(self) -> None:
        """Test that sleep delegates to asyncio.sleep."""
        source = TimeSource()
        start = time.monotonic()
        await source.sleep(0.1)
        elapsed = time.monotonic() - start

        # Should have slept approximately 0.1 seconds
        assert 0.05 <= elapsed < 0.5  # Allow some variance

    def test_implements_itime_source_interface(self) -> None:
        """Test that TimeSource implements ITimeSource interface."""
        source = TimeSource()
        assert isinstance(source, ITimeSource)


class MockTimeSource(ITimeSource):
    """Mock time source for testing TimeOverride."""

    def __init__(
        self,
        utc_time: datetime,
        local_time: datetime,
        unix_time: float,
        monotonic_time: float,
    ) -> None:
        """Initialize mock time source."""
        self._utc_time = utc_time
        self._local_time = local_time
        self._unix_time = unix_time
        self._monotonic_time = monotonic_time
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
        await asyncio.sleep(0)


class TestTimeOverride:
    """Test TimeOverride context manager."""

    @pytest.mark.asyncio
    @real_time(
        reason="Tests that TimeSource returns real system time before and after override"
    )
    async def test_override_active_within_context(self) -> None:
        """Test that override is active within context."""
        fixed_utc = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        fixed_local = datetime(2024, 1, 1, 12, 0, 0)
        fixed_unix = 1704110400.0
        fixed_monotonic = 1000.0

        mock_source = MockTimeSource(
            utc_time=fixed_utc,
            local_time=fixed_local,
            unix_time=fixed_unix,
            monotonic_time=fixed_monotonic,
        )

        source = TimeSource()

        # Before override, should use system time
        before_override_utc = source.now_utc()
        assert before_override_utc != fixed_utc

        # Within override context, should use mock
        async with TimeOverride(mock_source):
            assert source.now_utc() == fixed_utc
            assert source.now_local() == fixed_local
            assert source.unix_time_s() == fixed_unix
            assert source.monotonic_s() == fixed_monotonic

        # After override, should use system time again
        after_override_utc = source.now_utc()
        assert after_override_utc != fixed_utc

    @pytest.mark.asyncio
    async def test_override_sleep_delegates_to_mock(self) -> None:
        """Test that sleep delegates to override source."""
        mock_source = MockTimeSource(
            utc_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            local_time=datetime(2024, 1, 1, 12, 0, 0),
            unix_time=1704110400.0,
            monotonic_time=1000.0,
        )

        source = TimeSource()

        async with TimeOverride(mock_source):
            await source.sleep(1.5)

        assert len(mock_source._sleep_calls) == 1
        assert mock_source._sleep_calls[0] == 1.5

    @pytest.mark.asyncio
    async def test_override_does_not_leak_to_other_contexts(self) -> None:
        """Test that override does not leak to concurrent contexts."""
        fixed_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_source = MockTimeSource(
            utc_time=fixed_time,
            local_time=datetime(2024, 1, 1, 12, 0, 0),
            unix_time=1704110400.0,
            monotonic_time=1000.0,
        )

        source = TimeSource()

        async def task_with_override() -> datetime:
            async with TimeOverride(mock_source):
                await asyncio.sleep(0.01)  # Small delay
                return source.now_utc()

        async def task_without_override() -> datetime:
            await asyncio.sleep(0.01)  # Small delay
            return source.now_utc()

        # Run tasks concurrently
        results = await asyncio.gather(task_with_override(), task_without_override())

        # Task with override should get fixed time
        assert results[0] == fixed_time

        # Task without override should get system time (not fixed time)
        assert results[1] != fixed_time

    @pytest.mark.asyncio
    @real_time(
        reason="Tests that TimeSource returns real system time after nested overrides exit"
    )
    async def test_nested_overrides(self) -> None:
        """Test that nested overrides work correctly."""
        outer_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        inner_time = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)

        outer_mock = MockTimeSource(
            utc_time=outer_time,
            local_time=datetime(2024, 1, 1, 12, 0, 0),
            unix_time=1704110400.0,
            monotonic_time=1000.0,
        )

        inner_mock = MockTimeSource(
            utc_time=inner_time,
            local_time=datetime(2024, 1, 1, 13, 0, 0),
            unix_time=1704114000.0,
            monotonic_time=2000.0,
        )

        source = TimeSource()

        async with TimeOverride(outer_mock):
            assert source.now_utc() == outer_time

            async with TimeOverride(inner_mock):
                assert source.now_utc() == inner_time

            # After inner override exits, should use outer again
            assert source.now_utc() == outer_time

        # After outer override exits, should use system time
        assert source.now_utc() != outer_time
        assert source.now_utc() != inner_time

    @pytest.mark.asyncio
    async def test_parallel_execution_isolation(self) -> None:
        """Test that override contexts are isolated across concurrent async tasks."""
        fixed_time_1 = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        fixed_time_2 = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        fixed_time_3 = datetime(2024, 1, 1, 14, 0, 0, tzinfo=timezone.utc)

        mock_source_1 = MockTimeSource(
            utc_time=fixed_time_1,
            local_time=datetime(2024, 1, 1, 12, 0, 0),
            unix_time=1704110400.0,
            monotonic_time=1000.0,
        )
        mock_source_2 = MockTimeSource(
            utc_time=fixed_time_2,
            local_time=datetime(2024, 1, 1, 13, 0, 0),
            unix_time=1704114000.0,
            monotonic_time=2000.0,
        )
        mock_source_3 = MockTimeSource(
            utc_time=fixed_time_3,
            local_time=datetime(2024, 1, 1, 14, 0, 0),
            unix_time=1704117600.0,
            monotonic_time=3000.0,
        )

        source = TimeSource()

        async def task_with_override_1() -> datetime:
            async with TimeOverride(mock_source_1):
                await asyncio.sleep(0.01)
                return source.now_utc()

        async def task_with_override_2() -> datetime:
            async with TimeOverride(mock_source_2):
                await asyncio.sleep(0.01)
                return source.now_utc()

        async def task_with_override_3() -> datetime:
            async with TimeOverride(mock_source_3):
                await asyncio.sleep(0.01)
                return source.now_utc()

        async def task_without_override() -> datetime:
            await asyncio.sleep(0.01)
            return source.now_utc()

        # Run all tasks concurrently
        results = await asyncio.gather(
            task_with_override_1(),
            task_with_override_2(),
            task_with_override_3(),
            task_without_override(),
        )

        # Each task should get its own override time
        assert results[0] == fixed_time_1
        assert results[1] == fixed_time_2
        assert results[2] == fixed_time_3

        # Task without override should get system time (not any of the fixed times)
        assert results[3] != fixed_time_1
        assert results[3] != fixed_time_2
        assert results[3] != fixed_time_3

    @pytest.mark.asyncio
    async def test_override_scoping_multiple_instances(self) -> None:
        """Test that override affects all TimeSource instances within the same context."""
        fixed_utc = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_source = MockTimeSource(
            utc_time=fixed_utc,
            local_time=datetime(2024, 1, 1, 12, 0, 0),
            unix_time=1704110400.0,
            monotonic_time=1000.0,
        )

        # Create multiple TimeSource instances
        source1 = TimeSource()
        source2 = TimeSource()
        source3 = TimeSource()

        # Before override, all should use system time
        before_1 = source1.now_utc()
        before_2 = source2.now_utc()
        before_3 = source3.now_utc()

        assert before_1 != fixed_utc
        assert before_2 != fixed_utc
        assert before_3 != fixed_utc

        async with TimeOverride(mock_source):
            # All instances should use override
            assert source1.now_utc() == fixed_utc
            assert source2.now_utc() == fixed_utc
            assert source3.now_utc() == fixed_utc

        # After override, all should use system time again
        after_1 = source1.now_utc()
        after_2 = source2.now_utc()
        after_3 = source3.now_utc()

        assert after_1 != fixed_utc
        assert after_2 != fixed_utc
        assert after_3 != fixed_utc

    @pytest.mark.asyncio
    async def test_override_exit_on_exception(self) -> None:
        """Test that override is properly cleaned up even when exception occurs."""
        fixed_utc = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_source = MockTimeSource(
            utc_time=fixed_utc,
            local_time=datetime(2024, 1, 1, 12, 0, 0),
            unix_time=1704110400.0,
            monotonic_time=1000.0,
        )

        source = TimeSource()

        # Verify override is active
        try:
            async with TimeOverride(mock_source):
                assert source.now_utc() == fixed_utc
                raise ValueError("Test exception")
        except ValueError:
            pass

        # After exception, override should be cleaned up
        assert source.now_utc() != fixed_utc

    @pytest.mark.asyncio
    async def test_nested_overrides_with_different_values(self) -> None:
        """Test nested overrides with different time values restore correctly."""
        outer_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        middle_time = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        inner_time = datetime(2024, 1, 1, 14, 0, 0, tzinfo=timezone.utc)

        outer_mock = MockTimeSource(
            utc_time=outer_time,
            local_time=datetime(2024, 1, 1, 12, 0, 0),
            unix_time=1704110400.0,
            monotonic_time=1000.0,
        )
        middle_mock = MockTimeSource(
            utc_time=middle_time,
            local_time=datetime(2024, 1, 1, 13, 0, 0),
            unix_time=1704114000.0,
            monotonic_time=2000.0,
        )
        inner_mock = MockTimeSource(
            utc_time=inner_time,
            local_time=datetime(2024, 1, 1, 14, 0, 0),
            unix_time=1704117600.0,
            monotonic_time=3000.0,
        )

        source = TimeSource()

        async with TimeOverride(outer_mock):
            assert source.now_utc() == outer_time

            async with TimeOverride(middle_mock):
                assert source.now_utc() == middle_time

                async with TimeOverride(inner_mock):
                    assert source.now_utc() == inner_time

                # After inner exits, should restore to middle
                assert source.now_utc() == middle_time

            # After middle exits, should restore to outer
            assert source.now_utc() == outer_time

        # After outer exits, should use system time
        assert source.now_utc() != outer_time
        assert source.now_utc() != middle_time
        assert source.now_utc() != inner_time

    @pytest.mark.asyncio
    async def test_override_affects_all_time_methods(self) -> None:
        """Test that override affects all time-related methods consistently."""
        fixed_utc = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        fixed_local = datetime(2024, 1, 1, 12, 0, 0)
        fixed_unix = 1704110400.0
        fixed_monotonic = 1000.0

        mock_source = MockTimeSource(
            utc_time=fixed_utc,
            local_time=fixed_local,
            unix_time=fixed_unix,
            monotonic_time=fixed_monotonic,
        )

        source = TimeSource()

        async with TimeOverride(mock_source):
            # All methods should return override values
            assert source.now_utc() == fixed_utc
            assert source.now_local() == fixed_local
            assert source.unix_time_s() == fixed_unix
            assert source.monotonic_s() == fixed_monotonic

            # Sleep should delegate to mock
            await source.sleep(2.5)
            assert len(mock_source._sleep_calls) == 1
            assert mock_source._sleep_calls[0] == 2.5
