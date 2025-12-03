"""Unit tests for StatisticsAggregationService.

This module contains unit tests for the StatisticsAggregationService class
to verify basic functionality and edge cases.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from src.core.domain.statistics_filter import StatisticsFilter
from src.core.domain.traffic_leg import TrafficLeg
from src.core.domain.usage_record import UsageRecord
from src.core.services.in_memory_usage_store import InMemoryUsageStore
from src.core.services.statistics_aggregation_service import (
    StatisticsAggregationService,
)


@pytest.fixture
def store_and_service():
    """Create a store and service for testing."""
    with TemporaryDirectory() as tmpdir:
        store = InMemoryUsageStore(
            persistence_path=Path(tmpdir) / "test.json",
            flush_interval_seconds=60.0,
        )
        service = StatisticsAggregationService(store)
        yield store, service


def test_rolling_window_stats_basic(store_and_service):
    """Test basic rolling window statistics functionality."""
    store, service = store_and_service

    # Create records with timestamps spread over 10 minutes
    now = datetime.now()
    records = []

    for i in range(10):
        record = UsageRecord(
            id=str(uuid.uuid4()),
            timestamp=now - timedelta(minutes=i),
            session_id=f"session-{i}",
            turn_number=1,
            backend_type="openai",
            model="gpt-4",
            frontend_type="openai",
            leg=TrafficLeg.CLIENT_TO_PROXY,
            mutated_prompt_tokens=100,
            mutated_completion_tokens=50,
            total_tokens=150,
            http_status_code=200,
        )
        records.append(record)
        store.add_record(record)

    # Get 5-minute rolling window stats
    stats = asyncio.run(service.get_rolling_window_stats(window_minutes=5))

    # Should only include records from last 5 minutes (indices 0-4)
    assert stats.request_count == 5
    assert stats.time_window_seconds == 5 * 60.0


def test_rolling_window_stats_with_filters(store_and_service):
    """Test rolling window statistics with additional filters."""
    store, service = store_and_service

    # Create records with different backends
    now = datetime.now()

    for i in range(5):
        # OpenAI records
        record = UsageRecord(
            id=str(uuid.uuid4()),
            timestamp=now - timedelta(minutes=i),
            session_id=f"session-{i}",
            turn_number=1,
            backend_type="openai",
            model="gpt-4",
            frontend_type="openai",
            leg=TrafficLeg.CLIENT_TO_PROXY,
            total_tokens=100,
        )
        store.add_record(record)

        # Anthropic records
        record = UsageRecord(
            id=str(uuid.uuid4()),
            timestamp=now - timedelta(minutes=i),
            session_id=f"session-{i}",
            turn_number=1,
            backend_type="anthropic",
            model="claude-3",
            frontend_type="anthropic",
            leg=TrafficLeg.CLIENT_TO_PROXY,
            total_tokens=100,
        )
        store.add_record(record)

    # Get 10-minute rolling window stats for OpenAI only
    filters = StatisticsFilter(backend_type="openai")
    stats = asyncio.run(
        service.get_rolling_window_stats(window_minutes=10, filters=filters)
    )

    # Should only include OpenAI records
    assert stats.request_count == 5


def test_rolling_window_stats_invalid_window():
    """Test that invalid window size raises ValueError."""
    with TemporaryDirectory() as tmpdir:
        store = InMemoryUsageStore(
            persistence_path=Path(tmpdir) / "test.json",
            flush_interval_seconds=60.0,
        )
        service = StatisticsAggregationService(store)

        with pytest.raises(ValueError, match="window_minutes must be positive"):
            asyncio.run(service.get_rolling_window_stats(window_minutes=0))

        with pytest.raises(ValueError, match="window_minutes must be positive"):
            asyncio.run(service.get_rolling_window_stats(window_minutes=-5))


def test_status_code_breakdown_basic(store_and_service):
    """Test basic status code breakdown functionality."""
    store, service = store_and_service

    # Create records with different status codes
    for i in range(5):
        record = UsageRecord(
            id=str(uuid.uuid4()),
            timestamp=datetime.now(),
            session_id=f"session-{i}",
            turn_number=1,
            backend_type="openai",
            model="gpt-4",
            frontend_type="openai",
            leg=TrafficLeg.CLIENT_TO_PROXY,
            http_status_code=200 if i < 3 else 500,
        )
        store.add_record(record)

    # Get status code breakdown
    breakdown = asyncio.run(service.get_status_code_breakdown())

    # Should have one key for openai:gpt-4
    assert "openai:gpt-4" in breakdown
    assert breakdown["openai:gpt-4"][200] == 3
    assert breakdown["openai:gpt-4"][500] == 2


def test_empty_stats():
    """Test that empty store returns empty stats."""
    with TemporaryDirectory() as tmpdir:
        store = InMemoryUsageStore(
            persistence_path=Path(tmpdir) / "test.json",
            flush_interval_seconds=60.0,
        )
        service = StatisticsAggregationService(store)

        stats = asyncio.run(service.get_aggregated_stats())

        assert stats.request_count == 0
        assert stats.response_count == 0
        assert stats.unique_sessions == 0
        assert stats.total_tokens == 0
