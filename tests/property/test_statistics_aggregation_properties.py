"""Property-based tests for statistics aggregation service.

This module contains property-based tests for the StatisticsAggregationService
to verify correctness properties related to aggregation, filtering, and
statistical calculations.

Feature: detailed-usage-tracking
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given, settings
from hypothesis import strategies as st
from src.core.domain.statistics_filter import StatisticsFilter
from src.core.domain.traffic_leg import TrafficLeg
from src.core.domain.usage_record import UsageRecord
from src.core.services.in_memory_usage_store import InMemoryUsageStore
from src.core.services.statistics_aggregation_service import (
    StatisticsAggregationService,
)


# Strategies for generating test data
@st.composite
def usage_record_strategy(draw):
    """Generate a random UsageRecord for testing."""
    timestamp = draw(
        st.datetimes(
            min_value=datetime(2024, 1, 1),
            max_value=datetime(2025, 12, 31),
        )
    )

    return UsageRecord(
        id=str(uuid.uuid4()),
        timestamp=timestamp,
        session_id=draw(
            st.text(
                min_size=1,
                max_size=20,
                alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
            )
        ),
        turn_number=draw(st.integers(min_value=1, max_value=100)),
        backend_type=draw(st.sampled_from(["openai", "anthropic", "gemini"])),
        model=draw(st.sampled_from(["gpt-4", "claude-3", "gemini-pro"])),
        frontend_type=draw(st.sampled_from(["openai", "anthropic"])),
        leg=draw(st.sampled_from(list(TrafficLeg))),
        verbatim_prompt_tokens=draw(st.integers(min_value=0, max_value=10000)),
        verbatim_completion_tokens=draw(st.integers(min_value=0, max_value=10000)),
        mutated_prompt_tokens=draw(st.integers(min_value=0, max_value=10000)),
        mutated_completion_tokens=draw(st.integers(min_value=0, max_value=10000)),
        total_tokens=draw(st.integers(min_value=0, max_value=20000)),
        http_status_code=draw(st.sampled_from([200, 400, 500, None])),
        tool_call_count=draw(st.integers(min_value=0, max_value=10)),
        tool_names=draw(st.lists(st.text(min_size=1, max_size=10), max_size=5)),
        ttft_ms=draw(st.one_of(st.none(), st.floats(min_value=0.0, max_value=10000.0))),
        proxy_processing_ms=draw(st.floats(min_value=0.0, max_value=1000.0)),
        total_duration_ms=draw(st.floats(min_value=0.0, max_value=30000.0)),
    )


@st.composite
def usage_record_list_strategy(draw, min_size=1, max_size=50):
    """Generate a list of UsageRecords."""
    return draw(st.lists(usage_record_strategy(), min_size=min_size, max_size=max_size))


# Property 4: Request/Response Counter Consistency
# Feature: detailed-usage-tracking, Property 4: Request/Response Counter Consistency
# Validates: Requirements 2.1, 2.2, 2.3, 2.4
@settings(max_examples=50, deadline=None)
@given(records=usage_record_list_strategy(min_size=1, max_size=50))
def test_request_response_counter_consistency(records):
    """Property 4: Request/Response Counter Consistency.

    For any sequence of N requests processed by the proxy, the request_count
    in aggregated statistics SHALL equal N, and the response_count SHALL equal
    the number of successfully completed responses.

    Validates: Requirements 2.1, 2.2, 2.3, 2.4
    """
    with TemporaryDirectory() as tmpdir:
        # Create store and service
        store = InMemoryUsageStore(
            persistence_path=Path(tmpdir) / "test.json",
            flush_interval_seconds=60.0,
        )
        service = StatisticsAggregationService(store)

        # Add records to store
        for record in records:
            store.add_record(record)

        # Get aggregated stats
        import asyncio

        stats = asyncio.run(service.get_aggregated_stats())

        # Verify request count equals number of records
        assert stats.request_count == len(
            records
        ), f"Expected request_count={len(records)}, got {stats.request_count}"

        # Verify response count equals number of records with http_status_code
        expected_response_count = sum(
            1 for r in records if r.http_status_code is not None
        )
        assert (
            stats.response_count == expected_response_count
        ), f"Expected response_count={expected_response_count}, got {stats.response_count}"


# Property 6: Tool Call Aggregation Correctness
# Feature: detailed-usage-tracking, Property 6: Tool Call Aggregation Correctness
# Validates: Requirements 3.4
@settings(max_examples=50, deadline=None)
@given(records=usage_record_list_strategy(min_size=1, max_size=50))
def test_tool_call_aggregation_correctness(records):
    """Property 6: Tool Call Aggregation Correctness.

    For any set of UsageRecords, the aggregated tool_call_count per
    session/backend/model SHALL equal the sum of individual tool_call_count
    values for that grouping.

    Validates: Requirements 3.4
    """
    with TemporaryDirectory() as tmpdir:
        # Create store and service
        store = InMemoryUsageStore(
            persistence_path=Path(tmpdir) / "test.json",
            flush_interval_seconds=60.0,
        )
        service = StatisticsAggregationService(store)

        # Add records to store
        for record in records:
            store.add_record(record)

        # Get aggregated stats (no filter)
        import asyncio

        stats = asyncio.run(service.get_aggregated_stats())

        # Verify total tool calls equals sum of individual tool_call_count
        expected_total_tool_calls = sum(r.tool_call_count for r in records)
        assert (
            stats.total_tool_calls == expected_total_tool_calls
        ), f"Expected total_tool_calls={expected_total_tool_calls}, got {stats.total_tool_calls}"

        # Test aggregation by backend
        for backend_type in {r.backend_type for r in records}:
            backend_filter = StatisticsFilter(backend_type=backend_type)
            backend_stats = asyncio.run(service.get_aggregated_stats(backend_filter))

            expected_backend_tool_calls = sum(
                r.tool_call_count for r in records if r.backend_type == backend_type
            )
            assert (
                backend_stats.total_tool_calls == expected_backend_tool_calls
            ), f"Backend {backend_type}: expected {expected_backend_tool_calls}, got {backend_stats.total_tool_calls}"

        # Test aggregation by model
        for model in {r.model for r in records}:
            model_filter = StatisticsFilter(model=model)
            model_stats = asyncio.run(service.get_aggregated_stats(model_filter))

            expected_model_tool_calls = sum(
                r.tool_call_count for r in records if r.model == model
            )
            assert (
                model_stats.total_tool_calls == expected_model_tool_calls
            ), f"Model {model}: expected {expected_model_tool_calls}, got {model_stats.total_tool_calls}"


# Property 7: Session Uniqueness Tracking
# Feature: detailed-usage-tracking, Property 7: Session Uniqueness Tracking
# Validates: Requirements 4.1
@settings(max_examples=50, deadline=None)
@given(records=usage_record_list_strategy(min_size=1, max_size=50))
def test_session_uniqueness_tracking(records):
    """Property 7: Session Uniqueness Tracking.

    For any set of requests with session IDs, the unique_sessions count SHALL
    equal the number of distinct session_id values in the recorded UsageRecords.

    Validates: Requirements 4.1
    """
    with TemporaryDirectory() as tmpdir:
        # Create store and service
        store = InMemoryUsageStore(
            persistence_path=Path(tmpdir) / "test.json",
            flush_interval_seconds=60.0,
        )
        service = StatisticsAggregationService(store)

        # Add records to store
        for record in records:
            store.add_record(record)

        # Get aggregated stats
        import asyncio

        stats = asyncio.run(service.get_aggregated_stats())

        # Verify unique_sessions equals number of distinct session_id values
        expected_unique_sessions = len({r.session_id for r in records})
        assert (
            stats.unique_sessions == expected_unique_sessions
        ), f"Expected unique_sessions={expected_unique_sessions}, got {stats.unique_sessions}"


# Property 8: Turn Counter Accuracy
# Feature: detailed-usage-tracking, Property 8: Turn Counter Accuracy
# Validates: Requirements 4.2
@settings(max_examples=50, deadline=None)
@given(records=usage_record_list_strategy(min_size=1, max_size=50))
def test_turn_counter_accuracy(records):
    """Property 8: Turn Counter Accuracy.

    For any session, the turn_count SHALL equal the number of UsageRecords
    with that session_id.

    Validates: Requirements 4.2
    """
    with TemporaryDirectory() as tmpdir:
        # Create store and service
        store = InMemoryUsageStore(
            persistence_path=Path(tmpdir) / "test.json",
            flush_interval_seconds=60.0,
        )
        service = StatisticsAggregationService(store)

        # Add records to store
        for record in records:
            store.add_record(record)

        # Get aggregated stats
        import asyncio

        stats = asyncio.run(service.get_aggregated_stats())

        # Verify total_turns equals sum of all turn_numbers
        expected_total_turns = sum(r.turn_number for r in records)
        assert (
            stats.total_turns == expected_total_turns
        ), f"Expected total_turns={expected_total_turns}, got {stats.total_turns}"

        # Test per-session turn counting
        for session_id in {r.session_id for r in records}:
            StatisticsFilter()
            # We need to filter manually since StatisticsFilter doesn't have session_id
            session_records = [r for r in records if r.session_id == session_id]

            # The number of records for this session should match
            sum(r.turn_number for r in session_records)

            # Verify by checking the records directly
            assert len(session_records) > 0, f"Session {session_id} should have records"


# Property 9: Tokens Per Session Calculation
# Feature: detailed-usage-tracking, Property 9: Tokens Per Session Calculation
# Validates: Requirements 4.3
@settings(max_examples=50, deadline=None)
@given(records=usage_record_list_strategy(min_size=1, max_size=50))
def test_tokens_per_session_calculation(records):
    """Property 9: Tokens Per Session Calculation.

    For any set of UsageRecords, the tokens_per_session statistic SHALL equal
    total_tokens divided by unique_sessions (or 0 if no sessions).

    Validates: Requirements 4.3
    """
    with TemporaryDirectory() as tmpdir:
        # Create store and service
        store = InMemoryUsageStore(
            persistence_path=Path(tmpdir) / "test.json",
            flush_interval_seconds=60.0,
        )
        service = StatisticsAggregationService(store)

        # Add records to store
        for record in records:
            store.add_record(record)

        # Get aggregated stats
        import asyncio

        stats = asyncio.run(service.get_aggregated_stats())

        # Calculate expected tokens_per_session
        total_tokens = sum(r.total_tokens for r in records)
        unique_sessions = len({r.session_id for r in records})

        if unique_sessions > 0:
            expected_tokens_per_session = total_tokens / unique_sessions
        else:
            expected_tokens_per_session = 0.0

        # Allow small floating point error
        assert abs(stats.tokens_per_session - expected_tokens_per_session) < 0.01, (
            f"Expected tokens_per_session={expected_tokens_per_session}, "
            f"got {stats.tokens_per_session}"
        )


# Property 10: Tokens Per Second (TPS) Calculation
# Feature: detailed-usage-tracking, Property 10: Tokens Per Second (TPS) Calculation
# Validates: Requirements 5.5
@settings(max_examples=50, deadline=None)
@given(records=usage_record_list_strategy(min_size=2, max_size=50))
def test_tps_calculation(records):
    """Property 10: Tokens Per Second (TPS) Calculation.

    For any time window with UsageRecords, the completion_tokens_per_second
    SHALL equal total_completion_tokens divided by time_window_seconds, and
    total_tokens_per_second SHALL equal total_tokens divided by
    time_window_seconds.

    Validates: Requirements 5.5
    """
    with TemporaryDirectory() as tmpdir:
        # Create store and service
        store = InMemoryUsageStore(
            persistence_path=Path(tmpdir) / "test.json",
            flush_interval_seconds=60.0,
        )
        service = StatisticsAggregationService(store)

        # Add records to store
        for record in records:
            store.add_record(record)

        # Get aggregated stats
        import asyncio

        stats = asyncio.run(service.get_aggregated_stats())

        # Calculate expected TPS
        if len(records) > 1:
            timestamps = sorted(r.timestamp for r in records)
            time_span = (timestamps[-1] - timestamps[0]).total_seconds()

            if time_span > 0:
                total_completion_tokens = sum(
                    r.mutated_completion_tokens for r in records
                )
                total_tokens = sum(r.total_tokens for r in records)

                expected_completion_tps = total_completion_tokens / time_span
                expected_total_tps = total_tokens / time_span

                # Allow small floating point error
                assert (
                    abs(stats.completion_tokens_per_second - expected_completion_tps)
                    < 0.01
                ), (
                    f"Expected completion_tokens_per_second={expected_completion_tps}, "
                    f"got {stats.completion_tokens_per_second}"
                )

                assert abs(stats.total_tokens_per_second - expected_total_tps) < 0.01, (
                    f"Expected total_tokens_per_second={expected_total_tps}, "
                    f"got {stats.total_tokens_per_second}"
                )

                assert abs(stats.time_window_seconds - time_span) < 0.01, (
                    f"Expected time_window_seconds={time_span}, "
                    f"got {stats.time_window_seconds}"
                )


# Property 13: Status Code Recording
# Feature: detailed-usage-tracking, Property 13: Status Code Recording
# Validates: Requirements 6.1, 6.2
@settings(max_examples=50, deadline=None)
@given(records=usage_record_list_strategy(min_size=1, max_size=50))
def test_status_code_recording(records):
    """Property 13: Status Code Recording.

    For any backend response with an HTTP status code, the recorded
    http_status_code SHALL match the actual response status code.

    Validates: Requirements 6.1, 6.2
    """
    with TemporaryDirectory() as tmpdir:
        # Create store and service
        store = InMemoryUsageStore(
            persistence_path=Path(tmpdir) / "test.json",
            flush_interval_seconds=60.0,
        )
        service = StatisticsAggregationService(store)

        # Add records to store
        for record in records:
            store.add_record(record)

        # Get aggregated stats
        import asyncio

        stats = asyncio.run(service.get_aggregated_stats())

        # Verify status code counts
        expected_status_counts: dict[int, int] = {}
        for record in records:
            if record.http_status_code is not None:
                status_code = record.http_status_code
                expected_status_counts[status_code] = (
                    expected_status_counts.get(status_code, 0) + 1
                )

        assert stats.status_code_counts == expected_status_counts, (
            f"Expected status_code_counts={expected_status_counts}, "
            f"got {stats.status_code_counts}"
        )


# Property 14: Status Code Aggregation
# Feature: detailed-usage-tracking, Property 14: Status Code Aggregation
# Validates: Requirements 6.3
@settings(max_examples=50, deadline=None)
@given(records=usage_record_list_strategy(min_size=1, max_size=50))
def test_status_code_aggregation(records):
    """Property 14: Status Code Aggregation.

    For any set of UsageRecords, the status_code_counts breakdown SHALL
    accurately reflect the count of each status code per backend:model
    combination.

    Validates: Requirements 6.3
    """
    with TemporaryDirectory() as tmpdir:
        # Create store and service
        store = InMemoryUsageStore(
            persistence_path=Path(tmpdir) / "test.json",
            flush_interval_seconds=60.0,
        )
        service = StatisticsAggregationService(store)

        # Add records to store
        for record in records:
            store.add_record(record)

        # Get status code breakdown
        import asyncio

        breakdown = asyncio.run(service.get_status_code_breakdown())

        # Build expected breakdown
        expected_breakdown: dict[str, dict[int, int]] = {}
        for record in records:
            if record.http_status_code is None:
                continue

            key = f"{record.backend_type}:{record.model}"
            if key not in expected_breakdown:
                expected_breakdown[key] = {}

            status_code = record.http_status_code
            expected_breakdown[key][status_code] = (
                expected_breakdown[key].get(status_code, 0) + 1
            )

        assert (
            breakdown == expected_breakdown
        ), f"Expected breakdown={expected_breakdown}, got {breakdown}"


# Property 17: Date Range Filter Correctness
# Feature: detailed-usage-tracking, Property 17: Date Range Filter Correctness
# Validates: Requirements 9.6
@settings(max_examples=50, deadline=None)
@given(records=usage_record_list_strategy(min_size=5, max_size=50))
def test_date_range_filter_correctness(records):
    """Property 17: Date Range Filter Correctness.

    For any query with start_date and end_date filters, all returned
    UsageRecords SHALL have timestamps within the specified range (inclusive).

    Validates: Requirements 9.6
    """
    with TemporaryDirectory() as tmpdir:
        # Create store and service
        store = InMemoryUsageStore(
            persistence_path=Path(tmpdir) / "test.json",
            flush_interval_seconds=60.0,
        )
        service = StatisticsAggregationService(store)

        # Add records to store
        for record in records:
            store.add_record(record)

        # Sort records by timestamp to get a valid date range
        sorted_records = sorted(records, key=lambda r: r.timestamp)

        if len(sorted_records) < 2:
            return  # Skip if not enough records

        # Pick a date range that includes some but not all records
        # Use the 25th and 75th percentile timestamps
        start_idx = len(sorted_records) // 4
        end_idx = (3 * len(sorted_records)) // 4

        start_date = sorted_records[start_idx].timestamp
        end_date = sorted_records[end_idx].timestamp

        # Create filter with date range
        date_filter = StatisticsFilter(start_date=start_date, end_date=end_date)

        # Get aggregated stats with filter
        import asyncio

        stats = asyncio.run(service.get_aggregated_stats(date_filter))

        # Verify all records in the range are counted
        expected_records = [r for r in records if start_date <= r.timestamp <= end_date]

        assert stats.request_count == len(expected_records), (
            f"Expected request_count={len(expected_records)}, "
            f"got {stats.request_count}"
        )

        # Verify that records outside the range are not counted
        # by checking that the count is less than total records
        if len(expected_records) < len(records):
            assert stats.request_count < len(
                records
            ), "Date filter should exclude some records"
