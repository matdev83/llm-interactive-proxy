"""
Property-based tests for usage recording service.

**Feature: detailed-usage-tracking**

This module tests the correctness properties of the UsageRecordingService:
- Token association correctness
- Tool call count accuracy
- Timing metrics validity
- Backend-reported usage preservation
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from src.core.domain.traffic_leg import TrafficLeg
from src.core.services.in_memory_usage_store import InMemoryUsageStore
from src.core.services.usage_recording_service import UsageRecordingService
from tests.utils.hypothesis_config import property_test_settings

# ============================================================================
# Strategies for generating test data
# ============================================================================


@st.composite
def traffic_leg_strategy(draw: Any) -> TrafficLeg:
    """Generate a random TrafficLeg enum value."""
    return draw(st.sampled_from(list(TrafficLeg)))


@st.composite
def backend_reported_usage_strategy(draw: Any) -> dict[str, Any] | None:
    """Generate backend-reported usage data or None."""
    if draw(st.booleans()):
        return None

    prompt_tokens = draw(st.integers(min_value=0, max_value=10000))
    completion_tokens = draw(st.integers(min_value=0, max_value=10000))
    reasoning_tokens = draw(st.integers(min_value=0, max_value=1000))
    cached_tokens = draw(st.integers(min_value=0, max_value=5000))
    cost = draw(st.floats(min_value=0.0, max_value=100.0))

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "completion_tokens_details": {"reasoning_tokens": reasoning_tokens},
        "prompt_tokens_details": {
            "cached_tokens": cached_tokens,
            "audio_tokens": 0,
        },
        "cost": cost,
    }


# ============================================================================
# Property 3: Token Association Correctness
# ============================================================================


@given(
    session_id=st.text(min_size=1, max_size=50),
    backend_type=st.sampled_from(["openai", "anthropic", "gemini"]),
    model=st.sampled_from(["gpt-4", "claude-3", "gemini-pro"]),
    frontend_type=st.sampled_from(["openai", "anthropic"]),
    leg=traffic_leg_strategy(),
    prompt_tokens=st.integers(min_value=0, max_value=10000),
)
@property_test_settings()
async def test_property_3_token_association_correctness(
    session_id: str,
    backend_type: str,
    model: str,
    frontend_type: str,
    leg: TrafficLeg,
    prompt_tokens: int,
) -> None:
    """
    **Feature: detailed-usage-tracking, Property 3: Token Association Correctness**
    **Validates: Requirements 1.5, 1.6**

    Property 3: Token Association Correctness

    *For any* recorded UsageRecord, the backend_type and model fields SHALL be
    non-empty strings that match the actual backend and model used for the request.
    """
    # Create service with temporary store
    with tempfile.TemporaryDirectory() as tmp_dir:
        persistence_path = Path(tmp_dir) / "test_store.json"
        store = InMemoryUsageStore(persistence_path=persistence_path)
        service = UsageRecordingService(store)

        # Record request
        record_id = await service.record_request(
            session_id=session_id,
            backend_type=backend_type,
            model=model,
            frontend_type=frontend_type,
            leg=leg,
            prompt_tokens=prompt_tokens,
        )

        # Retrieve the record
        record = store.get_record_by_id(record_id)
        assert record is not None, "Record should exist after recording request"

        # Verify backend_type is non-empty and matches
        assert record.backend_type, "backend_type must be non-empty"
        assert (
            record.backend_type == backend_type
        ), "backend_type must match the provided value"

        # Verify model is non-empty and matches
        assert record.model, "model must be non-empty"
        assert record.model == model, "model must match the provided value"


# ============================================================================
# Property 5: Tool Call Count Accuracy
# ============================================================================


@given(
    session_id=st.text(min_size=1, max_size=50),
    backend_type=st.sampled_from(["openai", "anthropic", "gemini"]),
    model=st.sampled_from(["gpt-4", "claude-3", "gemini-pro"]),
    frontend_type=st.sampled_from(["openai", "anthropic"]),
    leg=traffic_leg_strategy(),
    prompt_tokens=st.integers(min_value=0, max_value=10000),
    completion_tokens=st.integers(min_value=0, max_value=10000),
    tool_call_count=st.integers(min_value=0, max_value=10),
)
@property_test_settings()
async def test_property_5_tool_call_count_accuracy(
    session_id: str,
    backend_type: str,
    model: str,
    frontend_type: str,
    leg: TrafficLeg,
    prompt_tokens: int,
    completion_tokens: int,
    tool_call_count: int,
) -> None:
    """
    **Feature: detailed-usage-tracking, Property 5: Tool Call Count Accuracy**
    **Validates: Requirements 3.1, 3.2, 3.3**

    Property 5: Tool Call Count Accuracy

    *For any* response containing tool calls, the recorded tool_call_count SHALL
    equal the actual number of tool calls in the response, and tool_names SHALL
    contain exactly the names of tools called.
    """
    # Create service with temporary store
    with tempfile.TemporaryDirectory() as tmp_dir:
        persistence_path = Path(tmp_dir) / "test_store.json"
        store = InMemoryUsageStore(persistence_path=persistence_path)
        service = UsageRecordingService(store)

        # Record request
        record_id = await service.record_request(
            session_id=session_id,
            backend_type=backend_type,
            model=model,
            frontend_type=frontend_type,
            leg=leg,
            prompt_tokens=prompt_tokens,
        )

        # Generate tool names matching the count
        actual_tool_names = [f"tool_{i}" for i in range(tool_call_count)]

        # Record response with tool calls
        await service.record_response(
            record_id=record_id,
            completion_tokens=completion_tokens,
            http_status_code=200,
            tool_call_count=tool_call_count,
            tool_names=actual_tool_names,
        )

        # Retrieve the record
        record = store.get_record_by_id(record_id)
        assert record is not None, "Record should exist after recording response"

        # Verify tool_call_count matches
        assert (
            record.tool_call_count == tool_call_count
        ), "tool_call_count must match the provided value"

        # Verify tool_names matches
        assert (
            record.tool_names == actual_tool_names
        ), "tool_names must match the provided list"

        # Verify tool_names length matches tool_call_count
        assert (
            len(record.tool_names) == tool_call_count
        ), "Length of tool_names must equal tool_call_count"


# ============================================================================
# Property 11: Timing Metrics Validity
# ============================================================================


@given(
    session_id=st.text(min_size=1, max_size=50),
    backend_type=st.sampled_from(["openai", "anthropic", "gemini"]),
    model=st.sampled_from(["gpt-4", "claude-3", "gemini-pro"]),
    frontend_type=st.sampled_from(["openai", "anthropic"]),
    leg=traffic_leg_strategy(),
    prompt_tokens=st.integers(min_value=0, max_value=10000),
    completion_tokens=st.integers(min_value=0, max_value=10000),
    ttft_ms=st.one_of(st.none(), st.floats(min_value=0.0, max_value=10000.0)),
    proxy_processing_ms=st.floats(min_value=0.0, max_value=5000.0),
    total_duration_ms=st.floats(min_value=0.0, max_value=30000.0),
)
@property_test_settings()
async def test_property_11_timing_metrics_validity(
    session_id: str,
    backend_type: str,
    model: str,
    frontend_type: str,
    leg: TrafficLeg,
    prompt_tokens: int,
    completion_tokens: int,
    ttft_ms: float | None,
    proxy_processing_ms: float,
    total_duration_ms: float,
) -> None:
    """
    **Feature: detailed-usage-tracking, Property 11: Timing Metrics Validity**
    **Validates: Requirements 5.1, 5.2, 5.3**

    Property 11: Timing Metrics Validity

    *For any* recorded UsageRecord with timing data, ttft_ms (if present) SHALL
    be non-negative, proxy_processing_ms SHALL be non-negative, and
    total_duration_ms SHALL be greater than or equal to proxy_processing_ms.
    """
    # Ensure total_duration_ms >= proxy_processing_ms
    if total_duration_ms < proxy_processing_ms:
        total_duration_ms = proxy_processing_ms

    # Create service with temporary store
    with tempfile.TemporaryDirectory() as tmp_dir:
        persistence_path = Path(tmp_dir) / "test_store.json"
        store = InMemoryUsageStore(persistence_path=persistence_path)
        service = UsageRecordingService(store)

        # Record request
        record_id = await service.record_request(
            session_id=session_id,
            backend_type=backend_type,
            model=model,
            frontend_type=frontend_type,
            leg=leg,
            prompt_tokens=prompt_tokens,
        )

        # Record response with timing metrics
        await service.record_response(
            record_id=record_id,
            completion_tokens=completion_tokens,
            http_status_code=200,
            ttft_ms=ttft_ms,
            proxy_processing_ms=proxy_processing_ms,
            total_duration_ms=total_duration_ms,
        )

        # Retrieve the record
        record = store.get_record_by_id(record_id)
        assert record is not None, "Record should exist after recording response"

        # Verify ttft_ms is non-negative if present
        if record.ttft_ms is not None:
            assert record.ttft_ms >= 0, "ttft_ms must be non-negative"

        # Verify proxy_processing_ms is non-negative
        assert (
            record.proxy_processing_ms >= 0
        ), "proxy_processing_ms must be non-negative"

        # Verify total_duration_ms is non-negative
        assert record.total_duration_ms >= 0, "total_duration_ms must be non-negative"

        # Verify total_duration_ms >= proxy_processing_ms
        assert (
            record.total_duration_ms >= record.proxy_processing_ms
        ), "total_duration_ms must be >= proxy_processing_ms"


# ============================================================================
# Property 16: Backend-Reported Usage Separation
# ============================================================================


@given(
    session_id=st.text(min_size=1, max_size=50),
    backend_type=st.sampled_from(["openai", "anthropic", "gemini"]),
    model=st.sampled_from(["gpt-4", "claude-3", "gemini-pro"]),
    frontend_type=st.sampled_from(["openai", "anthropic"]),
    leg=traffic_leg_strategy(),
    prompt_tokens=st.integers(min_value=0, max_value=10000),
    completion_tokens=st.integers(min_value=0, max_value=10000),
    backend_reported_usage=backend_reported_usage_strategy(),
)
@property_test_settings()
async def test_property_16_backend_reported_usage_separation(
    session_id: str,
    backend_type: str,
    model: str,
    frontend_type: str,
    leg: TrafficLeg,
    prompt_tokens: int,
    completion_tokens: int,
    backend_reported_usage: dict[str, Any] | None,
) -> None:
    """
    **Feature: detailed-usage-tracking, Property 16: Backend-Reported Usage Separation**
    **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5**

    Property 16: Backend-Reported Usage Separation

    *For any* backend response containing usage metadata, the recorded UsageRecord
    SHALL store the complete backend-reported usage in a dedicated
    `backend_reported_usage` field (as OpenRouterUsage), preserving all fields
    including: prompt_tokens, completion_tokens, total_tokens, reasoning_tokens,
    cached_tokens, audio_tokens, cost, and upstream_inference_cost.
    """
    # Create service with temporary store
    with tempfile.TemporaryDirectory() as tmp_dir:
        persistence_path = Path(tmp_dir) / "test_store.json"
        store = InMemoryUsageStore(persistence_path=persistence_path)
        service = UsageRecordingService(store)

        # Record request
        record_id = await service.record_request(
            session_id=session_id,
            backend_type=backend_type,
            model=model,
            frontend_type=frontend_type,
            leg=leg,
            prompt_tokens=prompt_tokens,
        )

        # Record response with backend-reported usage
        await service.record_response(
            record_id=record_id,
            completion_tokens=completion_tokens,
            http_status_code=200,
            backend_reported_usage=backend_reported_usage,
        )

        # Retrieve the record
        record = store.get_record_by_id(record_id)
        assert record is not None, "Record should exist after recording response"

        # Verify backend_reported_usage field exists
        assert hasattr(
            record, "backend_reported_usage"
        ), "Record must have backend_reported_usage field"

        if backend_reported_usage is None:
            # If no backend usage was provided, field should be None
            assert (
                record.backend_reported_usage is None
            ), "backend_reported_usage should be None when not provided"
        else:
            # If backend usage was provided, verify it's stored correctly
            assert (
                record.backend_reported_usage is not None
            ), "backend_reported_usage should not be None when provided"

            # Verify basic token fields are preserved
            assert (
                record.backend_reported_usage.prompt_tokens
                == backend_reported_usage["prompt_tokens"]
            ), "prompt_tokens must be preserved"
            assert (
                record.backend_reported_usage.completion_tokens
                == backend_reported_usage["completion_tokens"]
            ), "completion_tokens must be preserved"
            assert (
                record.backend_reported_usage.total_tokens
                == backend_reported_usage["total_tokens"]
            ), "total_tokens must be preserved"

            # Verify extended fields are preserved
            if "completion_tokens_details" in backend_reported_usage:
                assert (
                    record.backend_reported_usage.completion_tokens_details is not None
                ), "completion_tokens_details should be preserved"
                assert (
                    record.backend_reported_usage.completion_tokens_details.reasoning_tokens
                    == backend_reported_usage["completion_tokens_details"][
                        "reasoning_tokens"
                    ]
                ), "reasoning_tokens must be preserved"

            if "prompt_tokens_details" in backend_reported_usage:
                assert (
                    record.backend_reported_usage.prompt_tokens_details is not None
                ), "prompt_tokens_details should be preserved"
                assert (
                    record.backend_reported_usage.prompt_tokens_details.cached_tokens
                    == backend_reported_usage["prompt_tokens_details"]["cached_tokens"]
                ), "cached_tokens must be preserved"

            if "cost" in backend_reported_usage:
                assert (
                    record.backend_reported_usage.cost == backend_reported_usage["cost"]
                ), "cost must be preserved"

            # Verify backend-reported usage is separate from proxy-calculated tokens
            # (they can be different values)
            assert hasattr(
                record, "verbatim_prompt_tokens"
            ), "Record must have separate verbatim_prompt_tokens"
            assert hasattr(
                record, "mutated_prompt_tokens"
            ), "Record must have separate mutated_prompt_tokens"
