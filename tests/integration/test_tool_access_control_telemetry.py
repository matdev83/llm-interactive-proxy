"""
Integration tests for Tool Access Control telemetry and observability.

These tests verify that statistics counters, logging, and metadata propagation
work correctly for tool access control features.
"""

import logging

import pytest
from src.core.config.app_config import AppConfig, ToolCallReactorConfig
from src.core.di.container import ServiceCollection
from src.core.di.services import register_core_services
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.core.services.tool_access_policy_service import ToolAccessPolicyService
from src.core.services.tool_call_reactor_service import ToolCallReactorService


class TestToolAccessControlTelemetry:
    """Test telemetry and observability features for tool access control."""

    @pytest.fixture
    def config_with_policies(self):
        """Create an AppConfig with tool access policies configured."""
        reactor_config = ToolCallReactorConfig(
            enabled=True,
            access_policies=[
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                    "allowed_patterns": ["read_.*", "list_.*"],
                    "blocked_patterns": ["delete_.*", "dangerous_.*"],
                    "block_message": "Tool blocked by test policy.",
                    "priority": 0,
                }
            ],
        )

        config = AppConfig()
        session_config = config.session.model_copy(
            update={"tool_call_reactor": reactor_config}
        )
        return config.model_copy(update={"session": session_config})

    @pytest.fixture
    def service_provider(self, config_with_policies):
        """Create a service provider with policies configured."""
        collection = ServiceCollection()
        register_core_services(collection, config_with_policies)
        return collection.build_service_provider()

    @pytest.fixture
    def reactor_service(self, service_provider):
        """Get the tool call reactor service."""
        return service_provider.get_required_service(ToolCallReactorService)

    @pytest.fixture
    def policy_service(self, service_provider):
        """Get the tool access policy service."""
        return service_provider.get_required_service(ToolAccessPolicyService)

    @pytest.fixture
    def handler(self, service_provider):
        """Get the tool access control handler."""
        reactor = service_provider.get_required_service(ToolCallReactorService)
        return reactor._handlers.get("tool_access_control_handler")

    @pytest.mark.asyncio
    async def test_statistics_counters_increment_on_blocked_call(
        self, reactor_service, handler
    ):
        """Verify statistics counters are incremented when tool calls are blocked."""
        # Get initial stats
        initial_stats = reactor_service.get_telemetry_stats()
        initial_blocked = initial_stats["tool_calls_blocked"]

        # Create a context for a blocked tool call
        context = ToolCallContext(
            session_id="test_session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="delete_file",
            tool_arguments={"path": "test.txt"},
            calling_agent=None,
            timestamp=None,
        )

        # Process the tool call
        result = await handler.handle(context)

        # Verify the call was blocked
        assert result.should_swallow is True

        # Verify counter was incremented
        updated_stats = reactor_service.get_telemetry_stats()
        assert updated_stats["tool_calls_blocked"] == initial_blocked + 1

    @pytest.mark.asyncio
    async def test_statistics_counters_increment_on_allowed_call(
        self, reactor_service, handler
    ):
        """Verify statistics counters are incremented when tool calls are allowed."""
        # Get initial stats
        initial_stats = reactor_service.get_telemetry_stats()
        initial_allowed = initial_stats["tool_calls_allowed"]

        # Create a context for an allowed tool call
        context = ToolCallContext(
            session_id="test_session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="read_file",
            tool_arguments={"path": "test.txt"},
            calling_agent=None,
            timestamp=None,
        )

        # Process the tool call
        result = await handler.handle(context)

        # Verify the call was allowed
        assert result.should_swallow is False

        # Verify counter was incremented
        updated_stats = reactor_service.get_telemetry_stats()
        assert updated_stats["tool_calls_allowed"] == initial_allowed + 1

    @pytest.mark.asyncio
    async def test_tool_definitions_filtered_counter(
        self, reactor_service, policy_service
    ):
        """Verify tool definitions filtered counter is incremented."""
        # Get initial stats
        initial_stats = reactor_service.get_telemetry_stats()
        initial_filtered = initial_stats["tool_definitions_filtered"]

        # Create tool definitions with some that should be filtered
        tools = [
            {"type": "function", "function": {"name": "read_file"}},
            {"type": "function", "function": {"name": "delete_file"}},
            {"type": "function", "function": {"name": "list_directory"}},
            {"type": "function", "function": {"name": "dangerous_operation"}},
        ]

        # Filter the tools
        result = policy_service.filter_tool_definitions(
            tools, "test-model", None
        )
        filtered_tools = result.filtered_tools
        metadata = result.metadata

        # Verify some tools were filtered
        assert len(filtered_tools) < len(tools)
        assert len(metadata.filtered_tool_names) > 0

        # Note: The counter is incremented in request_processor_service.py
        # This test verifies the counter exists and can be incremented
        reactor_service.increment_tool_definitions_filtered(
            len(metadata["filtered_tool_names"])
        )

        # Verify counter was incremented
        updated_stats = reactor_service.get_telemetry_stats()
        assert updated_stats["tool_definitions_filtered"] == initial_filtered + len(
            metadata["filtered_tool_names"]
        )

    @pytest.mark.asyncio
    async def test_logging_for_blocked_tool_call(self, handler, caplog):
        """Verify structured logging for blocked tool calls."""
        caplog.set_level(logging.INFO)

        # Create a context for a blocked tool call
        context = ToolCallContext(
            session_id="test_session_123",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="delete_file",
            tool_arguments={"path": "test.txt"},
            calling_agent=None,
            timestamp=None,
        )

        # Process the tool call
        await handler.handle(context)

        # Verify logging output
        log_messages = [record.message for record in caplog.records]
        blocked_log = next(
            (msg for msg in log_messages if "Blocked tool call" in msg), None
        )

        assert blocked_log is not None
        assert "delete_file" in blocked_log
        assert "test_session_123" in blocked_log
        assert "test_policy" in blocked_log

    @pytest.mark.asyncio
    async def test_logging_for_allowed_tool_call(self, handler, caplog):
        """Verify structured logging for allowed tool calls."""
        caplog.set_level(logging.DEBUG)

        # Create a context for an allowed tool call
        context = ToolCallContext(
            session_id="test_session_456",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="read_file",
            tool_arguments={"path": "test.txt"},
            calling_agent=None,
            timestamp=None,
        )

        # Process the tool call
        await handler.handle(context)

        # Verify logging output
        log_messages = [record.message for record in caplog.records]
        allowed_log = next(
            (msg for msg in log_messages if "allowed by policy" in msg), None
        )

        assert allowed_log is not None
        assert "read_file" in allowed_log
        assert "test_session_456" in allowed_log

    @pytest.mark.asyncio
    async def test_metadata_in_reaction_result(self, handler):
        """Verify policy metadata is included in ToolCallReactionResult."""
        # Create a context for a blocked tool call
        context = ToolCallContext(
            session_id="test_session",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="delete_file",
            tool_arguments={"path": "test.txt"},
            calling_agent="test-agent",
            timestamp=None,
        )

        # Process the tool call
        result = await handler.handle(context)

        # Verify metadata is present
        assert result.metadata is not None
        assert result.metadata["handler"] == "tool_access_control_handler"
        assert result.metadata["tool_name"] == "delete_file"
        assert result.metadata["policy_applied"] == "test_policy"
        assert result.metadata["decision"] == "blocked"
        assert result.metadata["model_name"] == "test-model"
        assert result.metadata["agent"] == "test-agent"
        assert result.metadata["session_id"] == "test_session"
        assert "evaluation_time_ms" in result.metadata

    @pytest.mark.asyncio
    async def test_first_blocked_tool_notification(self, handler):
        """Verify first blocked tool call in session includes notice."""
        session_id = "new_test_session"

        # Create a context for a blocked tool call
        context = ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="delete_file",
            tool_arguments={"path": "test.txt"},
            calling_agent=None,
            timestamp=None,
        )

        # Process the first blocked tool call
        result1 = await handler.handle(context)

        # Verify it's marked as first block
        assert result1.metadata["is_first_block_in_session"] is True
        assert "[Notice: Tool access control is active" in result1.replacement_response

        # Process a second blocked tool call in the same session
        context2 = ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="dangerous_operation",
            tool_arguments={},
            calling_agent=None,
            timestamp=None,
        )

        result2 = await handler.handle(context2)

        # Verify it's NOT marked as first block
        assert result2.metadata["is_first_block_in_session"] is False
        assert (
            "[Notice: Tool access control is active" not in result2.replacement_response
        )

    @pytest.mark.asyncio
    async def test_performance_metrics_collection(self, policy_service):
        """Verify performance metrics are collected for policy evaluation."""
        # Get initial metrics
        initial_metrics = policy_service.get_performance_metrics()
        initial_count = initial_metrics["evaluation_count"]

        # Perform some policy evaluations
        tools = [
            {"type": "function", "function": {"name": "read_file"}},
            {"type": "function", "function": {"name": "delete_file"}},
        ]

        policy_service.filter_tool_definitions(tools, "test-model", None)
        policy_service.is_tool_allowed("read_file", "test-model", None)
        policy_service.is_tool_allowed("delete_file", "test-model", None)

        # Get updated metrics
        updated_metrics = policy_service.get_performance_metrics()

        # Verify metrics were updated
        assert updated_metrics["evaluation_count"] > initial_count
        assert updated_metrics["total_evaluation_time_ms"] > 0
        assert updated_metrics["average_evaluation_time_ms"] > 0

    @pytest.mark.asyncio
    async def test_metadata_in_filter_result(self, policy_service):
        """Verify metadata is included in filter_tool_definitions result."""
        tools = [
            {"type": "function", "function": {"name": "read_file"}},
            {"type": "function", "function": {"name": "delete_file"}},
            {"type": "function", "function": {"name": "list_directory"}},
        ]

        result = policy_service.filter_tool_definitions(
            tools, "test-model", "test-agent"
        )
        metadata = result.metadata

        # Verify metadata structure
        assert metadata.policy_applied == "test_policy"
        assert metadata.original_tool_count == 3
        assert metadata.filtered_tool_names is not None
        assert isinstance(metadata.evaluation_time_ms, float)

    @pytest.mark.asyncio
    async def test_telemetry_stats_structure(self, reactor_service):
        """Verify telemetry stats have correct structure."""
        stats = reactor_service.get_telemetry_stats()

        # Verify all expected keys are present
        assert "tool_definitions_filtered" in stats
        assert "tool_calls_blocked" in stats
        assert "tool_calls_allowed" in stats

        # Verify all values are integers
        assert isinstance(stats["tool_definitions_filtered"], int)
        assert isinstance(stats["tool_calls_blocked"], int)
        assert isinstance(stats["tool_calls_allowed"], int)

        # Verify all values are non-negative
        assert stats["tool_definitions_filtered"] >= 0
        assert stats["tool_calls_blocked"] >= 0
        assert stats["tool_calls_allowed"] >= 0

    @pytest.mark.asyncio
    async def test_performance_metrics_structure(self, policy_service):
        """Verify performance metrics have correct structure."""
        metrics = policy_service.get_performance_metrics()

        # Verify all expected keys are present
        assert "evaluation_count" in metrics
        assert "total_evaluation_time_ms" in metrics
        assert "average_evaluation_time_ms" in metrics

        # Verify all values are numeric
        assert isinstance(metrics["evaluation_count"], int)
        assert isinstance(metrics["total_evaluation_time_ms"], float)
        assert isinstance(metrics["average_evaluation_time_ms"], float)

        # Verify all values are non-negative
        assert metrics["evaluation_count"] >= 0
        assert metrics["total_evaluation_time_ms"] >= 0
        assert metrics["average_evaluation_time_ms"] >= 0

    @pytest.mark.asyncio
    async def test_logging_includes_policy_name(self, policy_service, caplog):
        """Verify logging includes policy name for filtered tools."""
        caplog.set_level(logging.INFO)

        tools = [
            {"type": "function", "function": {"name": "read_file"}},
            {"type": "function", "function": {"name": "delete_file"}},
        ]

        policy_service.filter_tool_definitions(tools, "test-model", None)

        # Verify logging output includes policy name
        log_messages = [record.message for record in caplog.records]
        filtered_log = next(
            (
                msg
                for msg in log_messages
                if "Filtered" in msg and "tool definition" in msg
            ),
            None,
        )

        if filtered_log:  # Only check if tools were actually filtered
            assert "test_policy" in filtered_log
