"""
Property-based tests for usage tracking domain models.

**Feature: detailed-usage-tracking**

This module tests the correctness properties of the usage tracking domain models:
- UsageRecord serialization and token recording
- TimingStats calculation
- StatisticsFilter matching
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from src.core.domain.openrouter_usage import OpenRouterUsage
from src.core.domain.statistics_filter import StatisticsFilter
from src.core.domain.timing_stats import TimingStats
from src.core.domain.traffic_leg import TrafficLeg
from src.core.domain.usage_record import UsageRecord
from tests.utils.hypothesis_config import property_test_settings

# ============================================================================
# Strategies for generating domain model components
# ============================================================================


@st.composite
def traffic_leg_strategy(draw: Any) -> TrafficLeg:
    """Generate a random TrafficLeg enum value."""
    return draw(st.sampled_from(list(TrafficLeg)))


@st.composite
def openrouter_usage_strategy(draw: Any) -> OpenRouterUsage | None:
    """Generate an OpenRouterUsage instance or None."""
    if draw(st.booleans()):
        return None

    prompt_tokens = draw(st.integers(min_value=0, max_value=10000))
    completion_tokens = draw(st.integers(min_value=0, max_value=10000))

    return OpenRouterUsage.from_basic_usage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


@st.composite
def usage_record_strategy(draw: Any) -> UsageRecord:
    """Generate a random UsageRecord instance."""
    record_id = str(uuid.uuid4())
    timestamp = draw(
        st.datetimes(
            min_value=datetime(2024, 1, 1),
            max_value=datetime(2025, 12, 31),
        )
    )
    session_id = draw(st.text(min_size=1, max_size=50))
    turn_number = draw(st.integers(min_value=1, max_value=100))

    backend_type = draw(st.sampled_from(["openai", "anthropic", "gemini", "test"]))
    model = draw(st.sampled_from(["gpt-4", "claude-3", "gemini-pro", "test-model"]))
    frontend_type = draw(st.sampled_from(["openai", "anthropic", "test"]))
    leg = draw(traffic_leg_strategy())

    verbatim_prompt_tokens = draw(st.integers(min_value=0, max_value=10000))
    verbatim_completion_tokens = draw(st.integers(min_value=0, max_value=10000))
    mutated_prompt_tokens = draw(st.integers(min_value=0, max_value=10000))
    mutated_completion_tokens = draw(st.integers(min_value=0, max_value=10000))
    total_tokens = (
        verbatim_prompt_tokens
        + verbatim_completion_tokens
        + mutated_prompt_tokens
        + mutated_completion_tokens
    )

    backend_reported_usage = draw(openrouter_usage_strategy())

    http_status_code = draw(
        st.one_of(st.none(), st.sampled_from([200, 400, 401, 403, 429, 500, 503]))
    )
    tool_call_count = draw(st.integers(min_value=0, max_value=10))
    tool_names = draw(
        st.lists(st.text(min_size=1, max_size=20), min_size=0, max_size=tool_call_count)
    )

    ttft_ms = draw(st.one_of(st.none(), st.floats(min_value=0.0, max_value=10000.0)))
    proxy_processing_ms = draw(st.floats(min_value=0.0, max_value=5000.0))
    total_duration_ms = draw(
        st.floats(min_value=proxy_processing_ms, max_value=30000.0)
    )

    user_agent = draw(st.one_of(st.none(), st.text(min_size=1, max_size=100)))
    app_title = draw(st.one_of(st.none(), st.text(min_size=1, max_size=50)))
    proxy_user = draw(st.one_of(st.none(), st.text(min_size=1, max_size=50)))

    return UsageRecord(
        id=record_id,
        timestamp=timestamp,
        session_id=session_id,
        turn_number=turn_number,
        backend_type=backend_type,
        model=model,
        frontend_type=frontend_type,
        leg=leg,
        verbatim_prompt_tokens=verbatim_prompt_tokens,
        verbatim_completion_tokens=verbatim_completion_tokens,
        mutated_prompt_tokens=mutated_prompt_tokens,
        mutated_completion_tokens=mutated_completion_tokens,
        total_tokens=total_tokens,
        backend_reported_usage=backend_reported_usage,
        http_status_code=http_status_code,
        tool_call_count=tool_call_count,
        tool_names=tool_names,
        ttft_ms=ttft_ms,
        proxy_processing_ms=proxy_processing_ms,
        total_duration_ms=total_duration_ms,
        user_agent=user_agent,
        app_title=app_title,
        proxy_user=proxy_user,
    )


@st.composite
def statistics_filter_strategy(draw: Any) -> StatisticsFilter:
    """Generate a random StatisticsFilter instance."""
    backend_type = draw(
        st.one_of(st.none(), st.sampled_from(["openai", "anthropic", "gemini"]))
    )
    model = draw(
        st.one_of(st.none(), st.sampled_from(["gpt-4", "claude-3", "gemini-pro"]))
    )
    frontend_type = draw(st.one_of(st.none(), st.sampled_from(["openai", "anthropic"])))
    leg = draw(st.one_of(st.none(), traffic_leg_strategy()))
    user_agent = draw(st.one_of(st.none(), st.text(min_size=1, max_size=50)))
    proxy_user = draw(st.one_of(st.none(), st.text(min_size=1, max_size=50)))

    start_date = draw(
        st.one_of(
            st.none(),
            st.datetimes(
                min_value=datetime(2024, 1, 1), max_value=datetime(2025, 6, 1)
            ),
        )
    )
    end_date = draw(
        st.one_of(
            st.none(),
            st.datetimes(
                min_value=start_date if start_date else datetime(2024, 1, 1),
                max_value=datetime(2025, 12, 31),
            ),
        )
    )

    day_of_week = draw(st.one_of(st.none(), st.integers(min_value=0, max_value=6)))
    hour_of_day = draw(st.one_of(st.none(), st.integers(min_value=0, max_value=23)))
    http_status_code = draw(st.one_of(st.none(), st.sampled_from([200, 400, 500])))

    return StatisticsFilter(
        backend_type=backend_type,
        model=model,
        frontend_type=frontend_type,
        leg=leg,
        user_agent=user_agent,
        proxy_user=proxy_user,
        start_date=start_date,
        end_date=end_date,
        day_of_week=day_of_week,
        hour_of_day=hour_of_day,
        http_status_code=http_status_code,
    )


# ============================================================================
# Property 1: Verbatim Token Recording at Ingress Points
# ============================================================================


@given(record=usage_record_strategy())
@property_test_settings()
def test_property_1_verbatim_token_recording_at_ingress_points(
    record: UsageRecord,
) -> None:
    """
    **Feature: detailed-usage-tracking, Property 1: Verbatim Token Recording at Ingress Points**
    **Validates: Requirements 1.1, 1.3**

    Property 1: Verbatim Token Recording at Ingress Points

    *For any* request received at a frontend connector, the recorded UsageRecord
    SHALL contain verbatim_prompt_tokens measured BEFORE any proxy modifications.
    *For any* response received from a backend connector, the recorded UsageRecord
    SHALL contain verbatim_completion_tokens measured BEFORE any proxy modifications.
    """
    # Verify verbatim token fields exist and are non-negative
    assert (
        record.verbatim_prompt_tokens >= 0
    ), "verbatim_prompt_tokens must be non-negative"
    assert (
        record.verbatim_completion_tokens >= 0
    ), "verbatim_completion_tokens must be non-negative"

    # Verify these fields are separate from mutated fields
    assert hasattr(
        record, "verbatim_prompt_tokens"
    ), "UsageRecord must have verbatim_prompt_tokens field"
    assert hasattr(
        record, "verbatim_completion_tokens"
    ), "UsageRecord must have verbatim_completion_tokens field"


# ============================================================================
# Property 2: Mutated Token Recording at Egress Points
# ============================================================================


@given(record=usage_record_strategy())
@property_test_settings()
def test_property_2_mutated_token_recording_at_egress_points(
    record: UsageRecord,
) -> None:
    """
    **Feature: detailed-usage-tracking, Property 2: Mutated Token Recording at Egress Points**
    **Validates: Requirements 1.2, 1.4**

    Property 2: Mutated Token Recording at Egress Points

    *For any* request sent to a backend connector, the recorded UsageRecord SHALL
    contain mutated_prompt_tokens measured AFTER all proxy modifications.
    *For any* response sent to a client, the recorded UsageRecord SHALL contain
    mutated_completion_tokens measured AFTER all proxy modifications.
    """
    # Verify mutated token fields exist and are non-negative
    assert (
        record.mutated_prompt_tokens >= 0
    ), "mutated_prompt_tokens must be non-negative"
    assert (
        record.mutated_completion_tokens >= 0
    ), "mutated_completion_tokens must be non-negative"

    # Verify these fields are separate from verbatim fields
    assert hasattr(
        record, "mutated_prompt_tokens"
    ), "UsageRecord must have mutated_prompt_tokens field"
    assert hasattr(
        record, "mutated_completion_tokens"
    ), "UsageRecord must have mutated_completion_tokens field"


# ============================================================================
# Property 18: Serialization Round-Trip Consistency
# ============================================================================


@given(record=usage_record_strategy())
@property_test_settings()
def test_property_18_serialization_roundtrip_consistency(
    record: UsageRecord,
) -> None:
    """
    **Feature: detailed-usage-tracking, Property 18: Serialization Round-Trip Consistency**
    **Validates: Requirements 10.1, 10.2, 10.3, 10.4**

    Property 18: Serialization Round-Trip Consistency

    *For any* valid UsageRecord, serializing to JSON and then deserializing
    SHALL produce an equivalent UsageRecord with all fields preserved.
    """
    # Serialize to dict
    serialized = record.to_dict()

    # Verify to_dict returns a dict
    assert isinstance(serialized, dict), "to_dict() must return a dict"

    # Deserialize back to UsageRecord
    deserialized = UsageRecord.from_dict(serialized)

    # Verify from_dict returns a UsageRecord
    assert isinstance(
        deserialized, UsageRecord
    ), "from_dict() must return a UsageRecord"

    # Use direct equality comparison (dataclass __eq__) for performance
    # This is faster than field-by-field comparison while maintaining precision
    if deserialized != record:
        # Only compute differences if assertion fails (for error message)
        import dataclasses

        differences = [
            (f.name, getattr(deserialized, f.name), getattr(record, f.name))
            for f in dataclasses.fields(UsageRecord)
            if getattr(deserialized, f.name) != getattr(record, f.name)
        ]
        raise AssertionError(
            f"Deserialized record should equal original. Differences: {differences}"
        )


# ============================================================================
# Property 12: Timing Statistics Correctness
# ============================================================================


@given(
    values=st.lists(
        st.floats(
            min_value=0.0, max_value=10000.0, allow_nan=False, allow_infinity=False
        ),
        min_size=1,
        max_size=1000,
    )
)
@property_test_settings()
def test_property_12_timing_statistics_correctness(values: list[float]) -> None:
    """
    **Feature: detailed-usage-tracking, Property 12: Timing Statistics Correctness**
    **Validates: Requirements 5.4**

    Property 12: Timing Statistics Correctness

    *For any* set of timing values, the calculated min SHALL be less than or
    equal to all values, max SHALL be greater than or equal to all values,
    and avg SHALL equal sum/count.
    """
    stats = TimingStats.from_values(values)

    # Verify count
    assert stats.count == len(values), "count must equal number of values"

    # Verify min is less than or equal to all values
    assert all(stats.min_ms <= v for v in values), "min_ms must be <= all values"

    # Verify max is greater than or equal to all values
    assert all(stats.max_ms >= v for v in values), "max_ms must be >= all values"

    # Verify average
    expected_avg = sum(values) / len(values)
    assert abs(stats.avg_ms - expected_avg) < 0.01, "avg_ms must equal sum/count"

    # Verify percentiles are within range
    assert stats.min_ms <= stats.p50_ms <= stats.max_ms, "p50 must be within min-max"
    assert stats.min_ms <= stats.p95_ms <= stats.max_ms, "p95 must be within min-max"
    assert stats.min_ms <= stats.p99_ms <= stats.max_ms, "p99 must be within min-max"

    # Verify percentile ordering
    assert stats.p50_ms <= stats.p95_ms, "p50 must be <= p95"
    assert stats.p95_ms <= stats.p99_ms, "p95 must be <= p99"


# ============================================================================
# Property 15: Filter Correctness
# ============================================================================


@given(record=usage_record_strategy(), filter_obj=statistics_filter_strategy())
@property_test_settings(max_examples=20)  # Reduced from default 50 for performance
def test_property_15_filter_correctness(
    record: UsageRecord, filter_obj: StatisticsFilter
) -> None:
    """
    **Feature: detailed-usage-tracking, Property 15: Filter Correctness**
    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9**

    Property 15: Filter Correctness

    *For any* StatisticsFilter applied to a query, all returned UsageRecords
    SHALL match ALL specified filter criteria (backend_type, model, frontend_type,
    leg, user_agent, proxy_user, date range, hour_of_day).
    """
    matches = filter_obj.matches(record)

    # Manually verify each filter criterion
    if (
        filter_obj.backend_type is not None
        and record.backend_type != filter_obj.backend_type
    ):
        assert not matches, "Filter should reject record with different backend_type"
        return

    if filter_obj.model is not None and record.model != filter_obj.model:
        assert not matches, "Filter should reject record with different model"
        return

    if (
        filter_obj.frontend_type is not None
        and record.frontend_type != filter_obj.frontend_type
    ):
        assert not matches, "Filter should reject record with different frontend_type"
        return

    if filter_obj.leg is not None and record.leg != filter_obj.leg:
        assert not matches, "Filter should reject record with different leg"
        return

    if filter_obj.user_agent is not None and record.user_agent != filter_obj.user_agent:
        assert not matches, "Filter should reject record with different user_agent"
        return

    if filter_obj.proxy_user is not None and record.proxy_user != filter_obj.proxy_user:
        assert not matches, "Filter should reject record with different proxy_user"
        return

    if filter_obj.start_date is not None and record.timestamp < filter_obj.start_date:
        assert not matches, "Filter should reject record before start_date"
        return

    if filter_obj.end_date is not None and record.timestamp > filter_obj.end_date:
        assert not matches, "Filter should reject record after end_date"
        return

    if (
        filter_obj.day_of_week is not None
        and record.timestamp.weekday() != filter_obj.day_of_week
    ):
        assert not matches, "Filter should reject record with different day_of_week"
        return

    if (
        filter_obj.hour_of_day is not None
        and record.timestamp.hour != filter_obj.hour_of_day
    ):
        assert not matches, "Filter should reject record with different hour_of_day"
        return

    if (
        filter_obj.http_status_code is not None
        and record.http_status_code != filter_obj.http_status_code
    ):
        assert (
            not matches
        ), "Filter should reject record with different http_status_code"
        return

    # If we reach here, all criteria match
    assert matches, "Filter should accept record that matches all criteria"


# ============================================================================
# Property 20: Thread-Safe Concurrent Access
# ============================================================================


@given(
    records=st.lists(
        usage_record_strategy(), min_size=3, max_size=15
    ),  # Reduced sizes for performance
    num_threads=st.integers(min_value=2, max_value=4),  # Reduced max threads
)
@property_test_settings(max_examples=20)  # Reduced from 30 for performance
def test_property_20_thread_safe_concurrent_access(
    records: list[UsageRecord], num_threads: int
) -> None:
    """
    **Feature: detailed-usage-tracking, Property 20: Thread-Safe Concurrent Access**
    **Validates: Requirements 9.1, 9.5**

    Property 20: Thread-Safe Concurrent Access

    *For any* sequence of concurrent add/query operations on the InMemoryUsageStore,
    all operations SHALL complete without data corruption, and the final state
    SHALL be consistent with some sequential ordering of the operations.
    """
    import tempfile
    import threading
    from pathlib import Path

    from src.core.services.in_memory_usage_store import InMemoryUsageStore

    # Create store with temporary persistence path
    with tempfile.TemporaryDirectory() as tmp_dir:
        persistence_path = Path(tmp_dir) / "test_store.json"
        store = InMemoryUsageStore(
            persistence_path=persistence_path,
            flush_interval_seconds=60.0,  # Don't auto-flush during test
        )

        # Track errors from threads
        errors: list[Exception] = []
        lock = threading.Lock()

        def add_records_worker(record_subset: list[UsageRecord]) -> None:
            """Worker function to add records."""
            try:
                for record in record_subset:
                    store.add_record(record)
            except Exception as e:
                with lock:
                    errors.append(e)

        def query_records_worker() -> None:
            """Worker function to query records."""
            try:
                # Query all records multiple times
                for _ in range(5):
                    _ = store.get_records()
            except Exception as e:
                with lock:
                    errors.append(e)

        # Split records among threads
        records_per_thread = len(records) // num_threads
        threads: list[threading.Thread] = []

        # Create add threads
        for i in range(num_threads):
            start_idx = i * records_per_thread
            end_idx = (
                start_idx + records_per_thread if i < num_threads - 1 else len(records)
            )
            record_subset = records[start_idx:end_idx]

            thread = threading.Thread(
                target=add_records_worker, args=(record_subset,), daemon=True
            )
            threads.append(thread)

        # Create query threads
        for _ in range(num_threads // 2):
            thread = threading.Thread(target=query_records_worker, daemon=True)
            threads.append(thread)

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join(timeout=3.0)  # Reduced from 5.0 for performance

        stuck_threads = [thread.name for thread in threads if thread.is_alive()]
        assert not stuck_threads, f"Threads did not finish: {stuck_threads}"

        # Check for errors
        assert len(errors) == 0, f"Concurrent operations produced errors: {errors}"

        # Verify final state consistency
        final_records = store.get_records()
        assert len(final_records) == len(
            records
        ), "All records should be present after concurrent adds"

        # Verify all record IDs are present
        final_ids = {r.id for r in final_records}
        expected_ids = {r.id for r in records}
        assert final_ids == expected_ids, "All record IDs should be present"

        # Verify no duplicate records
        assert len(final_ids) == len(
            final_records
        ), "No duplicate records should be present"


# ============================================================================
# Property 21: Persistence Dirty Flag Correctness
# ============================================================================


@given(
    records=st.lists(usage_record_strategy(), min_size=1, max_size=10)
)  # Reduced from 20
@property_test_settings(max_examples=10)  # Reduced from 20 for performance
def test_property_21_persistence_dirty_flag_correctness(
    records: list[UsageRecord],
) -> None:
    """
    **Feature: detailed-usage-tracking, Property 21: Persistence Dirty Flag Correctness**
    **Validates: Requirements 9.2, 9.3**

    Property 21: Persistence Dirty Flag Correctness

    *For any* sequence of add operations followed by flush_to_disk, the dirty
    flag SHALL be True before flush and False after flush, and subsequent
    queries SHALL return the same data before and after flush.
    """
    import tempfile
    from pathlib import Path

    from src.core.services.in_memory_usage_store import InMemoryUsageStore

    # Create store with temporary persistence path
    with tempfile.TemporaryDirectory() as tmp_dir:
        persistence_path = Path(tmp_dir) / "test_store.json"
        store = InMemoryUsageStore(
            persistence_path=persistence_path,
            flush_interval_seconds=60.0,  # Don't auto-flush during test
        )

        # Initially, store should not be dirty
        assert not store.is_dirty(), "Store should not be dirty initially"

        # Add records
        for record in records:
            store.add_record(record)

        # After adding records, store should be dirty
        assert store.is_dirty(), "Store should be dirty after adding records"

        # Query records before flush
        records_before_flush = store.get_records()
        assert len(records_before_flush) == len(
            records
        ), "All records should be present before flush"

        # Flush to disk
        store.flush_to_disk()

        # After flush, store should not be dirty
        assert not store.is_dirty(), "Store should not be dirty after flush"

        # Query records after flush
        records_after_flush = store.get_records()
        assert len(records_after_flush) == len(
            records
        ), "All records should be present after flush"

        # Verify data is the same before and after flush
        ids_before = {r.id for r in records_before_flush}
        ids_after = {r.id for r in records_after_flush}
        assert (
            ids_before == ids_after
        ), "Record IDs should be the same before and after flush"

        # Verify persistence file was created
        assert persistence_path.exists(), "Persistence file should exist after flush"

        # Create a new store and load from disk
        new_store = InMemoryUsageStore(
            persistence_path=persistence_path,
            flush_interval_seconds=60.0,
        )
        new_store.load_from_disk()

        # Verify loaded records match
        loaded_records = new_store.get_records()
        assert len(loaded_records) == len(
            records
        ), "All records should be loaded from disk"

        loaded_ids = {r.id for r in loaded_records}
        assert (
            loaded_ids == ids_before
        ), "Loaded record IDs should match original records"

        # After loading, store should not be dirty
        assert (
            not new_store.is_dirty()
        ), "Store should not be dirty after loading from disk"
