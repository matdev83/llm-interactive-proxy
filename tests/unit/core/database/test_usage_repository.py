"""Tests for UsageRecordRepository and database-backed usage tracking."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.core.database.models.usage import SessionMetricsTable, UsageRecordTable
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

        # Should have indexes
        assert len(table_args) >= 2, "Expected at least 2 composite indexes"
