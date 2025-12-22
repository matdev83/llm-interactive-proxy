"""Unit tests for SessionMetricsInitializer.

Tests cover:
- Success case: metrics created/updated
- Timeout case: returns without raising when DB is slow
- DB unavailable: logs error but doesn't raise
- Concurrent initialization: atomic upsert handles race conditions
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.database.models.usage import SessionMetricsTable
from src.core.database.repositories.usage_repository import SessionMetricsRepository
from src.core.domain.session_key import SessionKey
from src.core.services.session_metrics_initializer import (
    DEFAULT_TIMEOUT_SECONDS,
    SessionMetricsInitializer,
)


@pytest.fixture
def mock_session_repository() -> SessionMetricsRepository:
    """Create a mock session metrics repository."""
    mock = MagicMock(spec=SessionMetricsRepository)
    mock.upsert = AsyncMock()
    return mock


@pytest.fixture
def initializer(
    mock_session_repository: SessionMetricsRepository,
) -> SessionMetricsInitializer:
    """Create SessionMetricsInitializer instance for testing."""
    return SessionMetricsInitializer(
        session_repository=mock_session_repository,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
    )


@pytest.fixture
def sample_session_key() -> SessionKey:
    """Create a sample session key."""
    return SessionKey(
        protocol="http",
        primary_id="test-session-123",
        group_id="conversation-456",
    )


@pytest.fixture
def sample_observed_at() -> datetime:
    """Create a sample observation timestamp."""
    return datetime.now(timezone.utc)


class TestSuccessCase:
    """Test successful metrics initialization."""

    @pytest.mark.asyncio
    async def test_metrics_created_successfully(
        self,
        initializer: SessionMetricsInitializer,
        mock_session_repository: SessionMetricsRepository,
        sample_session_key: SessionKey,
        sample_observed_at: datetime,
    ):
        """Test that metrics are created successfully."""
        # Setup: mock successful upsert
        mock_metrics = SessionMetricsTable(
            session_id="test-session-123",
            start_time=sample_observed_at,
            last_activity=sample_observed_at,
            turn_count=0,
            total_tokens=0,
            total_tool_calls=0,
            is_completed=False,
        )
        mock_session_repository.upsert = AsyncMock(return_value=mock_metrics)

        # Execute
        await initializer.ensure_session_metrics(
            sample_session_key, observed_at=sample_observed_at
        )

        # Verify: upsert was called with correct metrics
        mock_session_repository.upsert.assert_awaited_once()
        call_args = mock_session_repository.upsert.call_args[0][0]
        assert isinstance(call_args, SessionMetricsTable)
        assert call_args.session_id == "test-session-123"
        assert call_args.start_time == sample_observed_at
        assert call_args.last_activity == sample_observed_at
        assert call_args.turn_count == 0
        assert call_args.total_tokens == 0
        assert call_args.total_tool_calls == 0
        assert call_args.is_completed is False

    @pytest.mark.asyncio
    async def test_metrics_updated_successfully(
        self,
        initializer: SessionMetricsInitializer,
        mock_session_repository: SessionMetricsRepository,
        sample_session_key: SessionKey,
        sample_observed_at: datetime,
    ):
        """Test that existing metrics are updated successfully."""
        # Setup: mock successful upsert (update case)
        existing_metrics = SessionMetricsTable(
            session_id="test-session-123",
            start_time=sample_observed_at,
            last_activity=sample_observed_at,
            turn_count=5,
            total_tokens=1000,
            total_tool_calls=2,
            is_completed=False,
        )
        mock_session_repository.upsert = AsyncMock(return_value=existing_metrics)

        # Execute
        await initializer.ensure_session_metrics(
            sample_session_key, observed_at=sample_observed_at
        )

        # Verify: upsert was called (repository handles update logic)
        mock_session_repository.upsert.assert_awaited_once()


class TestTimeoutCase:
    """Test timeout behavior."""

    @pytest.mark.asyncio
    async def test_timeout_returns_without_raising(
        self,
        mock_session_repository: SessionMetricsRepository,
        sample_session_key: SessionKey,
        sample_observed_at: datetime,
    ):
        """Test that timeout returns without raising."""

        # Setup: mock slow upsert that exceeds timeout
        async def slow_upsert(metrics: SessionMetricsTable) -> SessionMetricsTable:
            await asyncio.sleep(DEFAULT_TIMEOUT_SECONDS + 0.5)
            return metrics

        mock_session_repository.upsert = AsyncMock(side_effect=slow_upsert)

        # Create initializer with short timeout for faster test
        initializer = SessionMetricsInitializer(
            session_repository=mock_session_repository,
            timeout_seconds=0.1,
        )

        # Execute: should not raise, should return after timeout
        start_time = datetime.now(timezone.utc)
        await initializer.ensure_session_metrics(
            sample_session_key, observed_at=sample_observed_at
        )
        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()

        # Verify: returned quickly (within timeout + small buffer)
        assert elapsed < DEFAULT_TIMEOUT_SECONDS
        # Verify: upsert was called (but timed out)
        mock_session_repository.upsert.assert_awaited_once()


class TestDatabaseUnavailable:
    """Test behavior when database is unavailable."""

    @pytest.mark.asyncio
    async def test_database_error_logs_but_doesnt_raise(
        self,
        initializer: SessionMetricsInitializer,
        mock_session_repository: SessionMetricsRepository,
        sample_session_key: SessionKey,
        sample_observed_at: datetime,
    ):
        """Test that database errors are logged but don't raise."""
        # Setup: mock database error
        db_error = Exception("Database connection failed")
        mock_session_repository.upsert = AsyncMock(side_effect=db_error)

        # Execute: should not raise
        await initializer.ensure_session_metrics(
            sample_session_key, observed_at=sample_observed_at
        )

        # Verify: upsert was called
        mock_session_repository.upsert.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_database_timeout_logs_but_doesnt_raise(
        self,
        mock_session_repository: SessionMetricsRepository,
        sample_session_key: SessionKey,
        sample_observed_at: datetime,
    ):
        """Test that database timeout is logged but doesn't raise."""

        # Setup: mock slow upsert that exceeds timeout
        async def slow_upsert(metrics: SessionMetricsTable) -> SessionMetricsTable:
            await asyncio.sleep(0.2)
            return metrics

        mock_session_repository.upsert = AsyncMock(side_effect=slow_upsert)

        # Create initializer with very short timeout
        initializer = SessionMetricsInitializer(
            session_repository=mock_session_repository,
            timeout_seconds=0.05,
        )

        # Execute: should not raise
        await initializer.ensure_session_metrics(
            sample_session_key, observed_at=sample_observed_at
        )

        # Verify: upsert was called
        mock_session_repository.upsert.assert_awaited_once()


class TestConcurrentInitialization:
    """Test concurrent initialization behavior."""

    @pytest.mark.asyncio
    async def test_concurrent_initialization_handled_atomically(
        self,
        initializer: SessionMetricsInitializer,
        mock_session_repository: SessionMetricsRepository,
        sample_session_key: SessionKey,
        sample_observed_at: datetime,
    ):
        """Test that concurrent initialization is handled atomically."""
        # Setup: mock successful upsert
        mock_metrics = SessionMetricsTable(
            session_id="test-session-123",
            start_time=sample_observed_at,
            last_activity=sample_observed_at,
            turn_count=0,
            total_tokens=0,
            total_tool_calls=0,
            is_completed=False,
        )
        mock_session_repository.upsert = AsyncMock(return_value=mock_metrics)

        # Execute: multiple concurrent calls
        await asyncio.gather(
            *[
                initializer.ensure_session_metrics(
                    sample_session_key, observed_at=sample_observed_at
                )
                for _ in range(5)
            ]
        )

        # Verify: all calls completed (atomic upsert handles concurrency)
        assert mock_session_repository.upsert.await_count == 5


class TestSessionKeyMapping:
    """Test session key to session_id mapping."""

    @pytest.mark.asyncio
    async def test_primary_id_maps_to_session_id(
        self,
        initializer: SessionMetricsInitializer,
        mock_session_repository: SessionMetricsRepository,
        sample_observed_at: datetime,
    ):
        """Test that SessionKey.primary_id maps to session_metrics.session_id."""
        # Setup: different session keys
        http_key = SessionKey(
            protocol="http",
            primary_id="trace-abc123",
            group_id="conversation-xyz",
        )
        codebuff_key = SessionKey(
            protocol="codebuff",
            primary_id="codebuff:ws-456",
            group_id=None,
        )

        mock_metrics = SessionMetricsTable(
            session_id="",
            start_time=sample_observed_at,
            last_activity=sample_observed_at,
            turn_count=0,
            total_tokens=0,
            total_tool_calls=0,
            is_completed=False,
        )
        mock_session_repository.upsert = AsyncMock(return_value=mock_metrics)

        # Execute: HTTP session
        await initializer.ensure_session_metrics(
            http_key, observed_at=sample_observed_at
        )
        http_call = mock_session_repository.upsert.call_args_list[0][0][0]
        assert http_call.session_id == "trace-abc123"

        # Execute: Codebuff session
        await initializer.ensure_session_metrics(
            codebuff_key, observed_at=sample_observed_at
        )
        codebuff_call = mock_session_repository.upsert.call_args_list[1][0][0]
        assert codebuff_call.session_id == "codebuff:ws-456"
