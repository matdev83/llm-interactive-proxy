"""
Unit tests for ToolAccessControlHandler.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from src.core.config.app_config import ToolCallReactorConfig
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.core.services.tool_access_policy_service import ToolAccessPolicyService
from src.core.services.tool_call_handlers.tool_access_control_handler import (
    ToolAccessControlHandler,
)


class TestToolAccessControlHandler:
    """Test cases for ToolAccessControlHandler."""

    @pytest.fixture
    def policy_config_allow_all(self):
        """Create a config that allows all tools by default."""
        config = Mock(spec=ToolCallReactorConfig)
        config.access_policies = [
            {
                "name": "allow_all",
                "model_pattern": ".*",
                "default_policy": "allow",
                "allowed_patterns": [],
                "blocked_patterns": [],
                "block_message": "Tool not allowed.",
                "priority": 0,
            }
        ]
        return config

    @pytest.fixture
    def policy_config_block_dangerous(self):
        """Create a config that blocks dangerous tools."""
        config = Mock(spec=ToolCallReactorConfig)
        config.access_policies = [
            {
                "name": "block_dangerous",
                "model_pattern": ".*",
                "default_policy": "allow",
                "allowed_patterns": [],
                "blocked_patterns": ["delete_.*", "rm_.*", "remove_.*"],
                "block_message": "Dangerous operations are not allowed.",
                "priority": 0,
            }
        ]
        return config

    @pytest.fixture
    def policy_config_whitelist(self):
        """Create a config with whitelist mode (deny by default)."""
        config = Mock(spec=ToolCallReactorConfig)
        config.access_policies = [
            {
                "name": "whitelist_mode",
                "model_pattern": ".*",
                "default_policy": "deny",
                "allowed_patterns": ["read_.*", "list_.*", "search_.*"],
                "blocked_patterns": [],
                "block_message": "Only read-only tools are allowed.",
                "priority": 0,
            }
        ]
        return config

    @pytest.fixture
    def policy_config_model_specific(self):
        """Create a config with model-specific policies."""
        config = Mock(spec=ToolCallReactorConfig)
        config.access_policies = [
            {
                "name": "gpt4_restricted",
                "model_pattern": "gpt-4.*",
                "default_policy": "deny",
                "allowed_patterns": ["read_file", "list_directory"],
                "blocked_patterns": [],
                "block_message": "GPT-4 has limited tool access.",
                "priority": 10,
            },
            {
                "name": "claude_full_access",
                "model_pattern": "claude.*",
                "default_policy": "allow",
                "allowed_patterns": [],
                "blocked_patterns": [],
                "block_message": "Tool not allowed.",
                "priority": 5,
            },
        ]
        return config

    def test_handler_properties(self, policy_config_allow_all):
        """Test handler properties."""
        policy_service = ToolAccessPolicyService(policy_config_allow_all)
        handler = ToolAccessControlHandler(policy_service, priority=90)

        assert handler.name == "tool_access_control_handler"
        assert handler.priority == 90

    def test_handler_custom_priority(self, policy_config_allow_all):
        """Test handler with custom priority."""
        policy_service = ToolAccessPolicyService(policy_config_allow_all)
        handler = ToolAccessControlHandler(policy_service, priority=50)

        assert handler.priority == 50

    @pytest.mark.asyncio
    async def test_can_handle_returns_true_for_all_tools(self, policy_config_allow_all):
        """Test that can_handle returns True for all tool calls."""
        policy_service = ToolAccessPolicyService(policy_config_allow_all)
        handler = ToolAccessControlHandler(policy_service)

        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="any_tool",
            tool_arguments={},
        )

        can_handle = await handler.can_handle(context)
        assert can_handle is True

    @pytest.mark.asyncio
    async def test_handle_allows_tool_with_allow_all_policy(
        self, policy_config_allow_all
    ):
        """Test that handler allows tools when policy allows all."""
        policy_service = ToolAccessPolicyService(policy_config_allow_all)
        handler = ToolAccessControlHandler(policy_service)

        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="read_file",
            tool_arguments={"path": "test.txt"},
        )

        result = await handler.handle(context)

        assert result.should_swallow is False
        assert result.replacement_response is None
        assert result.metadata is not None
        assert result.metadata["handler"] == "tool_access_control_handler"
        assert result.metadata["decision"] == "allowed"
        assert result.metadata["tool_name"] == "read_file"

    @pytest.mark.asyncio
    async def test_handle_increments_telemetry_allowed_and_blocked(
        self, policy_config_block_dangerous
    ):
        """Reactor telemetry hooks fire on allow vs block paths."""
        policy_service = ToolAccessPolicyService(policy_config_block_dangerous)
        reactor = Mock()
        reactor.increment_tool_calls_allowed = Mock()
        reactor.increment_tool_calls_blocked = Mock()
        handler = ToolAccessControlHandler(
            policy_service, priority=90, reactor_service=reactor
        )

        allowed_ctx = ToolCallContext(
            session_id="telemetry_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="read_file",
            tool_arguments={"path": "test.txt"},
        )
        allowed_result = await handler.handle(allowed_ctx)
        assert allowed_result.should_swallow is False
        reactor.increment_tool_calls_allowed.assert_called_once()
        reactor.increment_tool_calls_blocked.assert_not_called()

        reactor.reset_mock()

        blocked_ctx = ToolCallContext(
            session_id="telemetry_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="delete_file",
            tool_arguments={"path": "test.txt"},
        )
        blocked_result = await handler.handle(blocked_ctx)
        assert blocked_result.should_swallow is True
        reactor.increment_tool_calls_blocked.assert_called_once()
        reactor.increment_tool_calls_allowed.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_blocks_dangerous_tool(self, policy_config_block_dangerous):
        """Test that handler blocks dangerous tools."""
        policy_service = ToolAccessPolicyService(policy_config_block_dangerous)
        handler = ToolAccessControlHandler(policy_service)

        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="delete_file",
            tool_arguments={"path": "test.txt"},
        )

        result = await handler.handle(context)

        assert result.should_swallow is True
        assert "Dangerous operations are not allowed." in result.replacement_response
        assert result.metadata is not None
        assert result.metadata["handler"] == "tool_access_control_handler"
        assert result.metadata["decision"] == "blocked"
        assert result.metadata["tool_name"] == "delete_file"
        assert result.metadata["session_id"] == "test_session"

    @pytest.mark.asyncio
    async def test_handle_allows_safe_tool_with_block_policy(
        self, policy_config_block_dangerous
    ):
        """Test that handler allows safe tools when only dangerous ones are blocked."""
        policy_service = ToolAccessPolicyService(policy_config_block_dangerous)
        handler = ToolAccessControlHandler(policy_service)

        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="read_file",
            tool_arguments={"path": "test.txt"},
        )

        result = await handler.handle(context)

        assert result.should_swallow is False
        assert result.replacement_response is None
        assert result.metadata["decision"] == "allowed"

    @pytest.mark.asyncio
    async def test_handle_whitelist_mode_allows_whitelisted_tool(
        self, policy_config_whitelist
    ):
        """Test that whitelist mode allows whitelisted tools."""
        policy_service = ToolAccessPolicyService(policy_config_whitelist)
        handler = ToolAccessControlHandler(policy_service)

        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="read_file",
            tool_arguments={"path": "test.txt"},
        )

        result = await handler.handle(context)

        assert result.should_swallow is False
        assert result.metadata["decision"] == "allowed"

    @pytest.mark.asyncio
    async def test_handle_whitelist_mode_blocks_non_whitelisted_tool(
        self, policy_config_whitelist
    ):
        """Test that whitelist mode blocks non-whitelisted tools."""
        policy_service = ToolAccessPolicyService(policy_config_whitelist)
        handler = ToolAccessControlHandler(policy_service)

        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="write_file",
            tool_arguments={"path": "test.txt", "content": "data"},
        )

        result = await handler.handle(context)

        assert result.should_swallow is True
        assert "Only read-only tools are allowed." in result.replacement_response
        assert result.metadata["decision"] == "blocked"

    @pytest.mark.asyncio
    async def test_handle_model_specific_policy_gpt4(
        self, policy_config_model_specific
    ):
        """Test that model-specific policies work for GPT-4."""
        policy_service = ToolAccessPolicyService(policy_config_model_specific)
        handler = ToolAccessControlHandler(policy_service)

        # GPT-4 should only allow read_file and list_directory
        context_allowed = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="gpt-4-turbo",
            full_response='{"content": "test"}',
            tool_name="read_file",
            tool_arguments={"path": "test.txt"},
        )

        result_allowed = await handler.handle(context_allowed)
        assert result_allowed.should_swallow is False

        # GPT-4 should block write_file
        context_blocked = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="gpt-4-turbo",
            full_response='{"content": "test"}',
            tool_name="write_file",
            tool_arguments={"path": "test.txt", "content": "data"},
        )

        result_blocked = await handler.handle(context_blocked)
        assert result_blocked.should_swallow is True
        assert "GPT-4 has limited tool access." in result_blocked.replacement_response

    @pytest.mark.asyncio
    async def test_handle_model_specific_policy_claude(
        self, policy_config_model_specific
    ):
        """Test that model-specific policies work for Claude."""
        policy_service = ToolAccessPolicyService(policy_config_model_specific)
        handler = ToolAccessControlHandler(policy_service)

        # Claude should allow all tools
        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="claude-3-opus",
            full_response='{"content": "test"}',
            tool_name="write_file",
            tool_arguments={"path": "test.txt", "content": "data"},
        )

        result = await handler.handle(context)
        assert result.should_swallow is False
        assert result.metadata["decision"] == "allowed"

    @pytest.mark.asyncio
    async def test_handle_with_agent_context(self, policy_config_allow_all):
        """Test that handler includes agent information in metadata."""
        policy_service = ToolAccessPolicyService(policy_config_allow_all)
        handler = ToolAccessControlHandler(policy_service)

        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="read_file",
            tool_arguments={"path": "test.txt"},
            calling_agent="production-agent",
        )

        result = await handler.handle(context)

        assert result.metadata["agent"] == "production-agent"

    @pytest.mark.asyncio
    async def test_handle_error_fails_open(self, policy_config_allow_all):
        """Test that handler fails open on errors."""
        policy_service = ToolAccessPolicyService(policy_config_allow_all)
        handler = ToolAccessControlHandler(policy_service)

        # Mock the policy service to raise an exception
        policy_service.is_tool_allowed = Mock(side_effect=Exception("Test error"))

        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="read_file",
            tool_arguments={"path": "test.txt"},
        )

        result = await handler.handle(context)

        # Should fail open (allow the tool call)
        assert result.should_swallow is False
        assert result.metadata["decision"] == "error_fail_open"
        assert "error" in result.metadata

    @pytest.mark.asyncio
    async def test_handle_includes_policy_metadata(self, policy_config_block_dangerous):
        """Test that handler includes policy metadata in results."""
        policy_service = ToolAccessPolicyService(policy_config_block_dangerous)
        handler = ToolAccessControlHandler(policy_service)

        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="delete_file",
            tool_arguments={"path": "test.txt"},
        )

        result = await handler.handle(context)

        assert result.metadata is not None
        assert result.metadata["policy_applied"] == "block_dangerous"
        assert result.metadata["reason"] == "blocked"
        assert result.metadata["model_name"] == "test_model"

    @pytest.mark.asyncio
    async def test_handle_multiple_blocked_patterns(self):
        """Test that handler blocks tools matching any blocked pattern."""
        config = Mock(spec=ToolCallReactorConfig)
        config.access_policies = [
            {
                "name": "multi_block",
                "model_pattern": ".*",
                "default_policy": "allow",
                "allowed_patterns": [],
                "blocked_patterns": ["delete_.*", "remove_.*", "drop_.*"],
                "block_message": "Destructive operations blocked.",
                "priority": 0,
            }
        ]

        policy_service = ToolAccessPolicyService(config)
        handler = ToolAccessControlHandler(policy_service)

        # Test each blocked pattern
        for tool_name in ["delete_file", "remove_directory", "drop_table"]:
            context = ToolCallContext(
                session_id="test_session",
                backend_name="test_backend",
                model_name="test_model",
                full_response='{"content": "test"}',
                tool_name=tool_name,
                tool_arguments={},
            )

            result = await handler.handle(context)
            assert result.should_swallow is True
            assert "Destructive operations blocked." in result.replacement_response

    @pytest.mark.asyncio
    async def test_handle_priority_ordering(self):
        """Test that handler respects priority ordering of policies."""
        config = Mock(spec=ToolCallReactorConfig)
        config.access_policies = [
            {
                "name": "low_priority",
                "model_pattern": ".*",
                "default_policy": "deny",
                "allowed_patterns": [],
                "blocked_patterns": [],
                "block_message": "Low priority block.",
                "priority": 1,
            },
            {
                "name": "high_priority",
                "model_pattern": ".*",
                "default_policy": "allow",
                "allowed_patterns": [],
                "blocked_patterns": [],
                "block_message": "High priority block.",
                "priority": 10,
            },
        ]

        policy_service = ToolAccessPolicyService(config)
        handler = ToolAccessControlHandler(policy_service)

        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="any_tool",
            tool_arguments={},
        )

        result = await handler.handle(context)

        # High priority policy should be applied (allow)
        assert result.should_swallow is False
        assert result.metadata["policy_applied"] == "high_priority"

    @pytest.mark.asyncio
    async def test_handle_custom_block_message(self):
        """Test that handler uses custom block messages from policy."""
        custom_message = "Custom block message for security reasons."
        config = Mock(spec=ToolCallReactorConfig)
        config.access_policies = [
            {
                "name": "custom_message_policy",
                "model_pattern": ".*",
                "default_policy": "deny",
                "allowed_patterns": [],
                "blocked_patterns": [],
                "block_message": custom_message,
                "priority": 0,
            }
        ]

        policy_service = ToolAccessPolicyService(config)
        handler = ToolAccessControlHandler(policy_service)

        context = ToolCallContext(
            session_id="test_session",
            backend_name="test_backend",
            model_name="test_model",
            full_response='{"content": "test"}',
            tool_name="any_tool",
            tool_arguments={},
        )

        result = await handler.handle(context)

        assert result.should_swallow is True
        assert custom_message in result.replacement_response
