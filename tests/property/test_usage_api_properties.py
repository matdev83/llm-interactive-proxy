"""
Property-based tests for usage tracking API endpoints.

**Feature: detailed-usage-tracking, Property 19: API Filter Application**
**Validates: Requirements 11.2, 11.3**

This module tests that API filter parameters correctly filter the returned
usage statistics and records.
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from src.core.domain.aggregated_stats import AggregatedStats
from src.core.domain.statistics_filter import StatisticsFilter
from src.core.domain.traffic_leg import TrafficLeg
from src.core.domain.usage_record import UsageRecord
from src.core.services.in_memory_usage_store import InMemoryUsageStore
from src.core.services.statistics_aggregation_service import (
    StatisticsAggregationService,
)


# Hypothesis strategies for generating test data
@st.composite
def usage_record_strategy(draw: st.DrawFn) -> UsageRecord:
    """Generate a random UsageRecord for testing.

    Args:
        draw: Hypothesis draw function

    Returns:
        Random UsageRecord instance
    """
    backend_types = ["openai", "anthropic", "gemini", "openrouter"]
    models = ["gpt-4", "claude-3-opus", "gemini-pro", "llama-2"]
    frontend_types = ["openai", "anthropic", "gemini"]
    legs = list(TrafficLeg)

    return UsageRecord(
        id=str(uuid.uuid4()),
        timestamp=draw(
            st.datetimes(
                min_value=datetime(2024, 1, 1), max_value=datetime(2024, 12, 31)
            )
        ),
        session_id=draw(
            st.text(
                min_size=1,
                max_size=20,
                alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
            )
        ),
        turn_number=draw(st.integers(min_value=1, max_value=100)),
        backend_type=draw(st.sampled_from(backend_types)),
        model=draw(st.sampled_from(models)),
        frontend_type=draw(st.sampled_from(frontend_types)),
        leg=draw(st.sampled_from(legs)),
        verbatim_prompt_tokens=draw(st.integers(min_value=0, max_value=10000)),
        verbatim_completion_tokens=draw(st.integers(min_value=0, max_value=10000)),
        mutated_prompt_tokens=draw(st.integers(min_value=0, max_value=10000)),
        mutated_completion_tokens=draw(st.integers(min_value=0, max_value=10000)),
        total_tokens=draw(st.integers(min_value=0, max_value=20000)),
        http_status_code=draw(
            st.sampled_from([200, 201, 400, 401, 403, 404, 429, 500, 502, 503])
        ),
        tool_call_count=draw(st.integers(min_value=0, max_value=10)),
        tool_names=draw(st.lists(st.text(min_size=1, max_size=20), max_size=5)),
        ttft_ms=draw(
            st.floats(
                min_value=0.0, max_value=5000.0, allow_nan=False, allow_infinity=False
            )
            | st.none()
        ),
        proxy_processing_ms=draw(
            st.floats(
                min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False
            )
        ),
        total_duration_ms=draw(
            st.floats(
                min_value=0.0, max_value=10000.0, allow_nan=False, allow_infinity=False
            )
        ),
        user_agent=draw(st.text(min_size=1, max_size=50) | st.none()),
        proxy_user=draw(st.text(min_size=1, max_size=20) | st.none()),
    )


@st.composite
def statistics_filter_strategy(draw: st.DrawFn) -> StatisticsFilter:
    """Generate a random StatisticsFilter for testing.

    Args:
        draw: Hypothesis draw function

    Returns:
        Random StatisticsFilter instance
    """
    backend_types = ["openai", "anthropic", "gemini", "openrouter"]
    models = ["gpt-4", "claude-3-opus", "gemini-pro", "llama-2"]
    frontend_types = ["openai", "anthropic", "gemini"]
    legs = list(TrafficLeg)

    return StatisticsFilter(
        backend_type=draw(st.sampled_from(backend_types) | st.none()),
        model=draw(st.sampled_from(models) | st.none()),
        frontend_type=draw(st.sampled_from(frontend_types) | st.none()),
        leg=draw(st.sampled_from(legs) | st.none()),
        user_agent=draw(st.text(min_size=1, max_size=50) | st.none()),
        proxy_user=draw(st.text(min_size=1, max_size=20) | st.none()),
        start_date=draw(
            st.datetimes(
                min_value=datetime(2024, 1, 1), max_value=datetime(2024, 6, 30)
            )
            | st.none()
        ),
        end_date=draw(
            st.datetimes(
                min_value=datetime(2024, 7, 1), max_value=datetime(2024, 12, 31)
            )
            | st.none()
        ),
        day_of_week=draw(st.integers(min_value=0, max_value=6) | st.none()),
        hour_of_day=draw(st.integers(min_value=0, max_value=23) | st.none()),
        http_status_code=draw(
            st.sampled_from([200, 201, 400, 401, 403, 404, 429, 500, 502, 503])
            | st.none()
        ),
    )


@pytest.mark.asyncio
@given(
    records=st.lists(usage_record_strategy(), min_size=1, max_size=50),
    filters=statistics_filter_strategy(),
)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_api_filter_application_property(
    records: list[UsageRecord],
    filters: StatisticsFilter,
) -> None:
    """
    Property 19: API Filter Application

    For any set of usage records and any filter, the aggregated statistics
    returned by the API SHALL reflect only the records matching the filter criteria.

    This property ensures that:
    1. All records in the aggregated stats match the filter
    2. No records that don't match the filter are included
    3. The counts and metrics are accurate for the filtered set

    **Validates: Requirements 11.2, 11.3**
    """
    # Create temporary directory for this test
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create in-memory store
        store = InMemoryUsageStore(
            persistence_path=Path(tmp_dir) / "test_usage.json",
            flush_interval_seconds=60.0,
        )

        # Add all records to the store
        for record in records:
            store.add_record(record)

        # Create statistics service
        stats_service = StatisticsAggregationService(store)

        # Get aggregated stats with filter
        stats: AggregatedStats = await stats_service.get_aggregated_stats(filters)

        # Manually filter records to verify
        expected_records = [r for r in records if filters.matches(r)]

        # Verify request count matches filtered records
        assert stats.request_count == len(expected_records), (
            f"Request count mismatch: expected {len(expected_records)}, "
            f"got {stats.request_count}"
        )

        # Verify unique sessions count
        expected_sessions = len({r.session_id for r in expected_records})
        assert stats.unique_sessions == expected_sessions, (
            f"Unique sessions mismatch: expected {expected_sessions}, "
            f"got {stats.unique_sessions}"
        )

        # Verify token counts
        expected_prompt_tokens = sum(r.mutated_prompt_tokens for r in expected_records)
        expected_completion_tokens = sum(
            r.mutated_completion_tokens for r in expected_records
        )
        expected_total_tokens = sum(r.total_tokens for r in expected_records)

        assert stats.total_prompt_tokens == expected_prompt_tokens, (
            f"Prompt tokens mismatch: expected {expected_prompt_tokens}, "
            f"got {stats.total_prompt_tokens}"
        )
        assert stats.total_completion_tokens == expected_completion_tokens, (
            f"Completion tokens mismatch: expected {expected_completion_tokens}, "
            f"got {stats.total_completion_tokens}"
        )
        assert stats.total_tokens == expected_total_tokens, (
            f"Total tokens mismatch: expected {expected_total_tokens}, "
            f"got {stats.total_tokens}"
        )

        # Verify tool call count
        expected_tool_calls = sum(r.tool_call_count for r in expected_records)
        assert stats.total_tool_calls == expected_tool_calls, (
            f"Tool calls mismatch: expected {expected_tool_calls}, "
            f"got {stats.total_tool_calls}"
        )

        # Verify status code counts
        expected_status_codes: dict[int, int] = {}
        for record in expected_records:
            if record.http_status_code is not None:
                status_code = record.http_status_code
                expected_status_codes[status_code] = (
                    expected_status_codes.get(status_code, 0) + 1
                )

        assert stats.status_code_counts == expected_status_codes, (
            f"Status code counts mismatch: expected {expected_status_codes}, "
            f"got {stats.status_code_counts}"
        )


@pytest.mark.asyncio
@given(
    records=st.lists(usage_record_strategy(), min_size=10, max_size=100),
)
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_backend_type_filter_property(
    records: list[UsageRecord],
) -> None:
    """
    Test that backend_type filter correctly filters records.

    For any set of records and a specific backend_type filter,
    all returned records SHALL have that backend_type.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create in-memory store
        store = InMemoryUsageStore(
            persistence_path=Path(tmp_dir) / "test_usage.json",
            flush_interval_seconds=60.0,
        )

        # Add all records to the store
        for record in records:
            store.add_record(record)

        # Get unique backend types from records
        backend_types = list({r.backend_type for r in records})
        if not backend_types:
            return  # Skip if no backend types

        # Test each backend type
        for backend_type in backend_types:
            filters = StatisticsFilter(backend_type=backend_type)
            stats_service = StatisticsAggregationService(store)
            stats = await stats_service.get_aggregated_stats(filters)

            # Verify all records match the backend type
            expected_records = [r for r in records if r.backend_type == backend_type]
            assert stats.request_count == len(expected_records), (
                f"Backend type filter failed for {backend_type}: "
                f"expected {len(expected_records)} records, got {stats.request_count}"
            )


@pytest.mark.asyncio
@given(
    records=st.lists(usage_record_strategy(), min_size=10, max_size=100),
)
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_date_range_filter_property(
    records: list[UsageRecord],
) -> None:
    """
    Test that date range filters correctly filter records.

    For any set of records and a date range filter,
    all returned records SHALL have timestamps within the range.
    """
    if not records:
        return

    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create in-memory store
        store = InMemoryUsageStore(
            persistence_path=Path(tmp_dir) / "test_usage.json",
            flush_interval_seconds=60.0,
        )

        # Add all records to the store
        for record in records:
            store.add_record(record)

        # Get min and max timestamps
        timestamps = [r.timestamp for r in records]
        min_timestamp = min(timestamps)
        max_timestamp = max(timestamps)

        # Create a filter with a date range in the middle
        mid_point = min_timestamp + (max_timestamp - min_timestamp) / 2
        start_date = mid_point - timedelta(days=30)
        end_date = mid_point + timedelta(days=30)

        filters = StatisticsFilter(start_date=start_date, end_date=end_date)
        stats_service = StatisticsAggregationService(store)
        stats = await stats_service.get_aggregated_stats(filters)

        # Verify all records are within the date range
        expected_records = [r for r in records if start_date <= r.timestamp <= end_date]
        assert stats.request_count == len(expected_records), (
            f"Date range filter failed: expected {len(expected_records)} records, "
            f"got {stats.request_count}"
        )


@pytest.mark.asyncio
@given(
    records=st.lists(usage_record_strategy(), min_size=10, max_size=100),
)
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_combined_filters_property(
    records: list[UsageRecord],
) -> None:
    """
    Test that multiple filters can be combined correctly.

    For any set of records and multiple filter criteria,
    all returned records SHALL match ALL specified criteria.
    """
    if not records:
        return

    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create in-memory store
        store = InMemoryUsageStore(
            persistence_path=Path(tmp_dir) / "test_usage.json",
            flush_interval_seconds=60.0,
        )

        # Add all records to the store
        for record in records:
            store.add_record(record)

        # Get a backend type and model that exist in the records
        backend_types = list({r.backend_type for r in records})
        models = list({r.model for r in records})

        if not backend_types or not models:
            return

        backend_type = backend_types[0]
        model = models[0]

        # Create filter with multiple criteria
        filters = StatisticsFilter(
            backend_type=backend_type,
            model=model,
        )
        stats_service = StatisticsAggregationService(store)
        stats = await stats_service.get_aggregated_stats(filters)

        # Verify all records match both criteria
        expected_records = [
            r for r in records if r.backend_type == backend_type and r.model == model
        ]
        assert stats.request_count == len(expected_records), (
            f"Combined filter failed: expected {len(expected_records)} records, "
            f"got {stats.request_count}"
        )
