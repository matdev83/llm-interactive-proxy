"""Tests for UsageRecordRepository and database-backed usage tracking."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from src.core.database.config import DatabaseConfig
from src.core.database.engine import DatabaseEngine
from src.core.database.models.usage import SessionMetricsTable, UsageRecordTable
from src.core.database.repositories.usage_repository import SessionMetricsRepository
from src.core.domain.traffic_leg import TrafficLeg
from src.core.domain.usage_record import UsageRecord


class TestUsageRecordTable:
    """Tests for UsageRecordTable model."""

    def test_from_domain_basic(self):
        """Test converting domain record to table record."""
        record = UsageRecord(
            id="test-id-123",
            timestamp=datetime.now(timezone.utc),
            session_id="session-456",
            turn_number=1,
            backend_type="openai",
            model="gpt-4",
            frontend_type="openai",
            leg=TrafficLeg.CLIENT_TO_PROXY,
            verbatim_prompt_tokens=100,
            mutated_prompt_tokens=110,
            verbatim_completion_tokens=50,
            mutated_completion_tokens=55,
            total_tokens=165,
            http_status_code=200,
            tool_call_count=2,
            tool_names=["search", "calculate"],
            ttft_ms=150.0,
            proxy_processing_ms=10.0,
            total_duration_ms=500.0,
            user_agent="TestAgent/1.0",
            app_title="TestApp",
            proxy_user="test@example.com",
        )

        table_record = UsageRecordTable.from_domain(record)

        assert table_record.id == record.id
        assert table_record.session_id == record.session_id
        assert table_record.backend_type == record.backend_type
        assert table_record.model == record.model
        assert table_record.leg == "CTP"
        assert table_record.verbatim_prompt_tokens == 100
        assert table_record.mutated_prompt_tokens == 110
        assert table_record.tool_call_count == 2
        assert '"search"' in table_record.tool_names_json
        assert '"calculate"' in table_record.tool_names_json

    def test_from_domain_with_backend_usage(self):
        """Test converting domain record with backend-reported usage."""
        from src.core.domain.openrouter_usage import OpenRouterUsage

        backend_usage = OpenRouterUsage(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost=0.015,
        )

        record = UsageRecord(
            id="test-id-123",
            timestamp=datetime.now(timezone.utc),
            session_id="session-456",
            turn_number=1,
            backend_type="openai",
            model="gpt-4",
            frontend_type="openai",
            leg=TrafficLeg.CLIENT_TO_PROXY,
            backend_reported_usage=backend_usage,
        )

        table_record = UsageRecordTable.from_domain(record)

        assert table_record.backend_reported_usage_json is not None
        assert '"prompt_tokens": 100' in table_record.backend_reported_usage_json
        assert '"cost": 0.015' in table_record.backend_reported_usage_json

    def test_to_domain_roundtrip(self):
        """Test that from_domain and to_domain are inverses."""
        from src.core.domain.openrouter_usage import OpenRouterUsage

        backend_usage = OpenRouterUsage(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost=0.015,
        )

        original = UsageRecord(
            id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
            session_id="session-456",
            turn_number=3,
            backend_type="anthropic",
            model="claude-3",
            frontend_type="anthropic",
            leg=TrafficLeg.PROXY_TO_BACKEND,
            verbatim_prompt_tokens=200,
            mutated_prompt_tokens=220,
            verbatim_completion_tokens=100,
            mutated_completion_tokens=110,
            total_tokens=330,
            backend_reported_usage=backend_usage,
            http_status_code=200,
            tool_call_count=1,
            tool_names=["execute_code"],
            ttft_ms=250.0,
            proxy_processing_ms=15.0,
            total_duration_ms=800.0,
            user_agent="Claude/1.0",
            app_title="ClaudeApp",
            proxy_user="user@test.com",
        )

        # Convert to table and back
        table_record = UsageRecordTable.from_domain(original)
        restored = table_record.to_domain()

        # Check all fields match
        assert restored.id == original.id
        assert restored.session_id == original.session_id
        assert restored.turn_number == original.turn_number
        assert restored.backend_type == original.backend_type
        assert restored.model == original.model
        assert restored.frontend_type == original.frontend_type
        assert restored.leg == original.leg
        assert restored.verbatim_prompt_tokens == original.verbatim_prompt_tokens
        assert restored.mutated_prompt_tokens == original.mutated_prompt_tokens
        assert restored.total_tokens == original.total_tokens
        assert restored.http_status_code == original.http_status_code
        assert restored.tool_call_count == original.tool_call_count
        assert restored.tool_names == original.tool_names
        assert restored.ttft_ms == original.ttft_ms
        assert restored.proxy_processing_ms == original.proxy_processing_ms
        assert restored.total_duration_ms == original.total_duration_ms
        assert restored.user_agent == original.user_agent
        assert restored.app_title == original.app_title
        assert restored.proxy_user == original.proxy_user

        # Check backend usage
        assert restored.backend_reported_usage is not None
        assert restored.backend_reported_usage.prompt_tokens == 100
        assert restored.backend_reported_usage.completion_tokens == 50
        assert restored.backend_reported_usage.cost == 0.015

    def test_from_domain_with_empty_tool_names(self):
        """Test converting record with empty tool names."""
        record = UsageRecord(
            id="test-id",
            timestamp=datetime.now(timezone.utc),
            session_id="session-1",
            turn_number=1,
            backend_type="openai",
            model="gpt-4",
            frontend_type="openai",
            leg=TrafficLeg.CLIENT_TO_PROXY,
            tool_names=[],
        )

        table_record = UsageRecordTable.from_domain(record)
        assert table_record.tool_names_json is None

    def test_to_domain_with_null_fields(self):
        """Test converting table record with null optional fields."""
        table_record = UsageRecordTable(
            id="test-id",
            timestamp=datetime.now(timezone.utc),
            session_id="session-1",
            turn_number=1,
            backend_type="openai",
            model="gpt-4",
            frontend_type="openai",
            leg="CTP",
            verbatim_prompt_tokens=0,
            verbatim_completion_tokens=0,
            mutated_prompt_tokens=0,
            mutated_completion_tokens=0,
            total_tokens=0,
            backend_reported_usage_json=None,
            http_status_code=None,
            tool_call_count=0,
            tool_names_json=None,
            ttft_ms=None,
            proxy_processing_ms=0.0,
            total_duration_ms=0.0,
            user_agent=None,
            app_title=None,
            proxy_user=None,
        )

        domain_record = table_record.to_domain()

        assert domain_record.backend_reported_usage is None
        assert domain_record.http_status_code is None
        assert domain_record.tool_names == []
        assert domain_record.ttft_ms is None
        assert domain_record.user_agent is None


class TestSessionMetricsTable:
    """Tests for SessionMetricsTable model."""

    def test_create_session_metrics(self):
        """Test creating session metrics table entry."""
        now = datetime.now(timezone.utc)
        metrics = SessionMetricsTable(
            session_id="session-123",
            start_time=now,
            last_activity=now,
            turn_count=5,
            total_tokens=1000,
            total_tool_calls=3,
            is_completed=False,
            backend_type="openai",
            model="gpt-4",
            proxy_user="test@example.com",
        )

        assert metrics.session_id == "session-123"
        assert metrics.turn_count == 5
        assert metrics.total_tokens == 1000
        assert metrics.is_completed is False

    def test_create_session_metrics_with_eos_fields(self):
        """Test creating session metrics with EoS fields."""
        now = datetime.now(timezone.utc)
        eos_time = datetime.now(timezone.utc)
        metrics = SessionMetricsTable(
            session_id="session-456",
            start_time=now,
            last_activity=now,
            turn_count=3,
            total_tokens=500,
            total_tool_calls=1,
            is_completed=True,
            backend_type="anthropic",
            model="claude-3",
            proxy_user="user@test.com",
            eos_emitted_at=eos_time,
            eos_signal_type="done_sentinel",
            eos_reason="Stream completed",
        )

        assert metrics.eos_emitted_at == eos_time
        assert metrics.eos_signal_type == "done_sentinel"
        assert metrics.eos_reason == "Stream completed"

    def test_create_session_metrics_with_null_eos_fields(self):
        """Test creating session metrics with null EoS fields."""
        now = datetime.now(timezone.utc)
        metrics = SessionMetricsTable(
            session_id="session-789",
            start_time=now,
            last_activity=now,
            turn_count=1,
            total_tokens=100,
            total_tool_calls=0,
            is_completed=False,
            eos_emitted_at=None,
            eos_signal_type=None,
            eos_reason=None,
        )

        assert metrics.eos_emitted_at is None
        assert metrics.eos_signal_type is None
        assert metrics.eos_reason is None


class TestUsageRecordTableIndexes:
    """Tests to verify table has proper indexes defined."""

    def test_table_has_indexes(self):
        """Verify that indexes are defined on the table."""
        # Check that __table_args__ contains Index definitions
        table_args = UsageRecordTable.__table_args__

        # Should have multiple indexes
        assert len(table_args) >= 6, "Expected at least 6 composite indexes"

        # Check for specific index names
        index_names = [idx.name for idx in table_args if hasattr(idx, "name")]
        assert "idx_usage_records_timestamp" in index_names
        assert "idx_usage_records_session_timestamp" in index_names
        assert "idx_usage_records_backend_model" in index_names


class TestSessionMetricsTableIndexes:
    """Tests to verify session metrics table has proper indexes defined."""

    def test_table_has_indexes(self):
        """Verify that indexes are defined on the table."""
        table_args = SessionMetricsTable.__table_args__

        # Should have indexes (last_activity, user_activity, eos_emitted_at)
        assert len(table_args) >= 3, "Expected at least 3 composite indexes"

        # Check for specific index names
        index_names = [idx.name for idx in table_args if hasattr(idx, "name")]
        assert "idx_session_metrics_last_activity" in index_names
        assert "idx_session_metrics_user_activity" in index_names
        assert "idx_session_metrics_eos_emitted_at" in index_names


class TestSessionMetricsRepositoryEoS:
    """Tests for SessionMetricsRepository EoS methods."""

    @pytest.fixture
    async def engine(self) -> DatabaseEngine:
        """Create in-memory database engine for testing."""
        config = DatabaseConfig(url="sqlite+aiosqlite:///:memory:")
        engine = DatabaseEngine(config)
        await engine.initialize()
        yield engine
        await engine.close()

    @pytest.fixture
    def repository(self, engine: DatabaseEngine) -> SessionMetricsRepository:
        """Create session metrics repository for testing."""
        return SessionMetricsRepository(engine)

    @pytest.fixture
    async def sample_metrics(
        self, repository: SessionMetricsRepository
    ) -> SessionMetricsTable:
        """Create a sample session metrics entry."""
        now = datetime.now(timezone.utc)
        metrics = SessionMetricsTable(
            session_id="test-session-123",
            start_time=now,
            last_activity=now,
            turn_count=5,
            total_tokens=1000,
            total_tool_calls=3,
            is_completed=False,
            backend_type="openai",
            model="gpt-4",
            proxy_user="test@example.com",
        )
        return await repository.upsert(metrics)

    @pytest.mark.asyncio
    async def test_claim_eos_emission_succeeds_when_not_claimed(
        self, repository: SessionMetricsRepository, sample_metrics: SessionMetricsTable
    ):
        """Test that claim_eos_emission succeeds when eos_emitted_at is NULL."""
        emitted_at = datetime.now(timezone.utc)
        signal_type = "done_sentinel"
        reason = "Stream completed"

        result = await repository.claim_eos_emission(
            sample_metrics.session_id, emitted_at, signal_type, reason
        )

        assert result is True

        # Verify the claim was persisted
        updated = await repository.get_by_id(sample_metrics.session_id)
        assert updated is not None
        # SQLite stores naive datetime, so compare timestamps
        assert updated.eos_emitted_at is not None
        assert (
            abs(
                (
                    updated.eos_emitted_at.replace(tzinfo=timezone.utc) - emitted_at
                ).total_seconds()
            )
            < 1
        )
        assert updated.eos_signal_type == signal_type
        assert updated.eos_reason == reason
        # Verify is_completed is set to True per design.md requirement
        assert updated.is_completed is True

    @pytest.mark.asyncio
    async def test_claim_eos_emission_fails_when_already_claimed(
        self, repository: SessionMetricsRepository, sample_metrics: SessionMetricsTable
    ):
        """Test that claim_eos_emission fails when eos_emitted_at is already set."""
        # First claim succeeds
        first_emitted_at = datetime.now(timezone.utc)
        first_result = await repository.claim_eos_emission(
            sample_metrics.session_id, first_emitted_at, "done_sentinel", "First claim"
        )
        assert first_result is True

        # Second claim fails
        second_emitted_at = datetime.now(timezone.utc)
        second_result = await repository.claim_eos_emission(
            sample_metrics.session_id,
            second_emitted_at,
            "finish_reason",
            "Second claim",
        )
        assert second_result is False

        # Verify first claim is still present
        updated = await repository.get_by_id(sample_metrics.session_id)
        assert updated is not None
        # SQLite stores naive datetime, so compare timestamps
        assert updated.eos_emitted_at is not None
        assert (
            abs(
                (
                    updated.eos_emitted_at.replace(tzinfo=timezone.utc)
                    - first_emitted_at
                ).total_seconds()
            )
            < 1
        )
        assert updated.eos_signal_type == "done_sentinel"

    @pytest.mark.asyncio
    async def test_has_ended_returns_false_when_not_ended(
        self, repository: SessionMetricsRepository, sample_metrics: SessionMetricsTable
    ):
        """Test that has_ended returns False when eos_emitted_at is NULL."""
        result = await repository.has_ended(sample_metrics.session_id)
        assert result is False

    @pytest.mark.asyncio
    async def test_has_ended_returns_true_when_ended(
        self, repository: SessionMetricsRepository, sample_metrics: SessionMetricsTable
    ):
        """Test that has_ended returns True when eos_emitted_at is set."""
        # Claim EoS emission
        emitted_at = datetime.now(timezone.utc)
        await repository.claim_eos_emission(
            sample_metrics.session_id, emitted_at, "done_sentinel", "Test"
        )

        # Check has_ended
        result = await repository.has_ended(sample_metrics.session_id)
        assert result is True

    @pytest.mark.asyncio
    async def test_has_ended_returns_false_for_nonexistent_session(
        self, repository: SessionMetricsRepository
    ):
        """Test that has_ended returns False for nonexistent session."""
        result = await repository.has_ended("nonexistent-session")
        assert result is False

    @pytest.mark.asyncio
    async def test_claim_eos_emission_returns_false_when_session_metrics_dont_exist(
        self, repository: SessionMetricsRepository
    ):
        """Test that claim_eos_emission returns False when session metrics don't exist."""
        emitted_at = datetime.now(timezone.utc)
        signal_type = "done_sentinel"
        reason = "Stream completed"

        # Attempt to claim EoS for a nonexistent session
        result = await repository.claim_eos_emission(
            "nonexistent-session-id", emitted_at, signal_type, reason
        )

        # Should return False since no rows were updated
        assert result is False

        # Verify no session metrics were created
        metrics = await repository.get_by_id("nonexistent-session-id")
        assert metrics is None

    @pytest.mark.asyncio
    async def test_claim_eos_emission_atomicity_under_concurrency(
        self, repository: SessionMetricsRepository, sample_metrics: SessionMetricsTable
    ):
        """Test that only one concurrent claim succeeds."""
        import asyncio

        emitted_at = datetime.now(timezone.utc)

        # Create multiple concurrent claims
        async def claim() -> bool:
            return await repository.claim_eos_emission(
                sample_metrics.session_id,
                emitted_at,
                "done_sentinel",
                "Concurrent claim",
            )

        # Run 10 concurrent claims
        results = await asyncio.gather(*[claim() for _ in range(10)])

        # Only one should succeed
        assert sum(results) == 1

        # Verify the claim was persisted
        updated = await repository.get_by_id(sample_metrics.session_id)
        assert updated is not None
        # SQLite stores naive datetime, so compare timestamps
        assert updated.eos_emitted_at is not None
        assert (
            abs(
                (
                    updated.eos_emitted_at.replace(tzinfo=timezone.utc) - emitted_at
                ).total_seconds()
            )
            < 1
        )
