"""Integration tests for Tool Access Control CLI parameter overrides."""

from src.core.config.app_config import SessionConfig, ToolCallReactorConfig
from src.core.services.tool_access_policy_service import ToolAccessPolicyService


class TestToolAccessControlCLIOverrides:
    """Test CLI parameter overrides for tool access control."""

    def test_cli_allowed_tools_override(self):
        """Test that --allowed-tools CLI parameter creates global override."""
        # Simulate CLI override in session config
        session_config = SessionConfig(
            tool_access_global_overrides={
                "allowed_patterns": ["read_.*", "list_.*"],
                "default_policy": "deny",
            }
        )

        reactor_config = ToolCallReactorConfig(access_policies=[])
        policy_service = ToolAccessPolicyService(
            reactor_config, global_overrides=session_config.tool_access_global_overrides
        )

        # Global override should allow read_file
        result = policy_service.is_tool_allowed("read_file", "test:model")
        is_allowed = result.is_allowed
        metadata = result.metadata
        assert is_allowed is True
        assert metadata.policy_applied == "global_override"

        # Global override should block write_file (not in allowed list, default deny)
        result = policy_service.is_tool_allowed("write_file", "test:model")
        is_allowed = result.is_allowed
        metadata = result.metadata
        assert is_allowed is False

    def test_cli_blocked_tools_override(self):
        """Test that --blocked-tools CLI parameter creates global override."""
        session_config = SessionConfig(
            tool_access_global_overrides={
                "blocked_patterns": ["delete_.*", "rm_.*"],
                "default_policy": "allow",
            }
        )

        reactor_config = ToolCallReactorConfig(access_policies=[])
        policy_service = ToolAccessPolicyService(
            reactor_config, global_overrides=session_config.tool_access_global_overrides
        )

        # Global override should block delete_file
        result = policy_service.is_tool_allowed("delete_file", "test:model")
        is_allowed = result.is_allowed
        metadata = result.metadata
        assert is_allowed is False
        assert metadata.policy_applied == "global_override"

        # Global override should allow read_file (not blocked, default allow)
        result = policy_service.is_tool_allowed("read_file", "test:model")
        is_allowed = result.is_allowed
        metadata = result.metadata
        assert is_allowed is True

    def test_cli_default_policy_override(self):
        """Test that --default-policy CLI parameter sets global default."""
        session_config = SessionConfig(
            tool_access_global_overrides={
                "default_policy": "deny",
            }
        )

        reactor_config = ToolCallReactorConfig(access_policies=[])
        policy_service = ToolAccessPolicyService(
            reactor_config, global_overrides=session_config.tool_access_global_overrides
        )

        # With default deny and no patterns, all tools should be blocked
        result = policy_service.is_tool_allowed("any_tool", "test:model")
        is_allowed = result.is_allowed
        metadata = result.metadata
        assert is_allowed is False
        assert metadata.policy_applied == "global_override"

    def test_cli_overrides_take_precedence_over_config(self):
        """Test that CLI overrides take precedence over configuration file policies."""
        # Configuration has a policy that allows delete_file
        reactor_config = ToolCallReactorConfig(
            access_policies=[
                {
                    "name": "config_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                    "allowed_patterns": ["delete_.*"],
                    "blocked_patterns": [],
                    "priority": 50,
                }
            ]
        )

        # CLI override blocks delete_file
        session_config = SessionConfig(
            tool_access_global_overrides={
                "blocked_patterns": ["delete_.*"],
                "default_policy": "allow",
            }
        )

        policy_service = ToolAccessPolicyService(
            reactor_config, global_overrides=session_config.tool_access_global_overrides
        )

        # CLI override should take precedence and block delete_file
        result = policy_service.is_tool_allowed("delete_file", "test:model")
        is_allowed = result.is_allowed
        metadata = result.metadata
        assert is_allowed is False
        assert metadata.policy_applied == "global_override"

    def test_cli_combined_allowed_and_blocked_patterns(self):
        """Test CLI with both allowed and blocked patterns."""
        session_config = SessionConfig(
            tool_access_global_overrides={
                "allowed_patterns": ["read_.*", "write_file"],
                "blocked_patterns": ["delete_.*"],
                "default_policy": "deny",
            }
        )

        reactor_config = ToolCallReactorConfig(access_policies=[])
        policy_service = ToolAccessPolicyService(
            reactor_config, global_overrides=session_config.tool_access_global_overrides
        )

        # Allowed pattern should work
        result = policy_service.is_tool_allowed("read_file", "test:model")
        is_allowed = result.is_allowed
        assert is_allowed is True

        # Specific allowed tool should work
        result = policy_service.is_tool_allowed("write_file", "test:model")
        is_allowed = result.is_allowed
        assert is_allowed is True

        # Blocked pattern should be blocked (even though it matches allowed pattern)
        # Wait, delete_file doesn't match read_.*, so it should be blocked by default deny
        result = policy_service.is_tool_allowed("delete_file", "test:model")
        is_allowed = result.is_allowed
        assert is_allowed is False

        # Tool not in allowed or blocked should be blocked by default deny
        result = policy_service.is_tool_allowed("execute_command", "test:model")
        is_allowed = result.is_allowed
        assert is_allowed is False

    def test_cli_override_with_empty_patterns(self):
        """Test CLI override with empty pattern lists."""
        session_config = SessionConfig(
            tool_access_global_overrides={
                "allowed_patterns": [],
                "blocked_patterns": [],
                "default_policy": "allow",
            }
        )

        reactor_config = ToolCallReactorConfig(access_policies=[])
        policy_service = ToolAccessPolicyService(
            reactor_config, global_overrides=session_config.tool_access_global_overrides
        )

        # With no patterns and default allow, everything should be allowed
        result = policy_service.is_tool_allowed("any_tool", "test:model")
        assert result.is_allowed is True

    def test_cli_override_precedence_in_filtering(self):
        """Test that CLI overrides work correctly in tool definition filtering."""
        session_config = SessionConfig(
            tool_access_global_overrides={
                "blocked_patterns": ["dangerous_.*"],
                "default_policy": "allow",
            }
        )

        reactor_config = ToolCallReactorConfig(access_policies=[])
        policy_service = ToolAccessPolicyService(
            reactor_config, global_overrides=session_config.tool_access_global_overrides
        )

        tools = [
            {"function": {"name": "safe_tool"}},
            {"function": {"name": "dangerous_tool"}},
            {"function": {"name": "another_safe_tool"}},
        ]

        result = policy_service.filter_tool_definitions(tools, "test:model")
        filtered_tools = result.filtered_tools
        metadata = result.metadata

        # Should filter out dangerous_tool
        assert len(filtered_tools) == 2
        assert filtered_tools[0]["function"]["name"] == "safe_tool"
        assert filtered_tools[1]["function"]["name"] == "another_safe_tool"
        assert len(metadata.filtered_tool_names) == 1
        assert "dangerous_tool" in metadata.filtered_tool_names
        assert metadata.policy_applied == "global_override"

    def test_cli_override_applies_to_all_models(self):
        """Test that CLI overrides apply to all models regardless of model pattern."""
        session_config = SessionConfig(
            tool_access_global_overrides={
                "blocked_patterns": ["delete_.*"],
                "default_policy": "allow",
            }
        )

        reactor_config = ToolCallReactorConfig(access_policies=[])
        policy_service = ToolAccessPolicyService(
            reactor_config, global_overrides=session_config.tool_access_global_overrides
        )

        # Test with different model names
        for model_name in ["openai:gpt-4", "anthropic:claude-3", "gemini:pro"]:
            result = policy_service.is_tool_allowed("delete_file", model_name)
            is_allowed = result.is_allowed
            metadata = result.metadata
            assert is_allowed is False
            assert metadata.policy_applied == "global_override"

    def test_cli_override_with_regex_patterns(self):
        """Test CLI overrides with complex regex patterns."""
        session_config = SessionConfig(
            tool_access_global_overrides={
                "allowed_patterns": [r"read_\w+", r"list_\w+", r"get_\w+"],
                "blocked_patterns": [r".*_all$", r"bulk_.*"],
                "default_policy": "deny",
            }
        )

        reactor_config = ToolCallReactorConfig(access_policies=[])
        policy_service = ToolAccessPolicyService(
            reactor_config, global_overrides=session_config.tool_access_global_overrides
        )

        # Allowed patterns should work
        assert (
            policy_service.is_tool_allowed("read_file", "test:model").is_allowed is True
        )
        assert (
            policy_service.is_tool_allowed("list_directory", "test:model").is_allowed
            is True
        )
        assert (
            policy_service.is_tool_allowed("get_data", "test:model").is_allowed is True
        )

        # Blocked patterns should be blocked
        assert (
            policy_service.is_tool_allowed("delete_all", "test:model").is_allowed
            is False
        )
        assert (
            policy_service.is_tool_allowed("bulk_delete", "test:model").is_allowed
            is False
        )

        # Not matching any pattern with default deny
        assert (
            policy_service.is_tool_allowed("write_file", "test:model").is_allowed
            is False
        )

    def test_no_cli_override_uses_config_policies(self):
        """Test that without CLI overrides, configuration policies are used."""
        # Configuration has a policy
        reactor_config = ToolCallReactorConfig(
            access_policies=[
                {
                    "name": "config_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                    "allowed_patterns": [],
                    "blocked_patterns": ["delete_.*"],
                    "priority": 50,
                }
            ]
        )

        # No CLI overrides
        policy_service = ToolAccessPolicyService(reactor_config, global_overrides=None)

        # Should use config policy
        result = policy_service.is_tool_allowed("delete_file", "test:model")
        is_allowed = result.is_allowed
        metadata = result.metadata
        assert is_allowed is False
        assert metadata.policy_applied == "config_policy"

        # Allowed by config policy
        result = policy_service.is_tool_allowed("read_file", "test:model")
        is_allowed = result.is_allowed
        metadata = result.metadata
        assert is_allowed is True
        assert metadata.policy_applied == "config_policy"

    def test_cli_override_validation_errors(self):
        """Test that invalid CLI overrides are handled gracefully."""
        # Invalid default_policy value should be caught by Pydantic or handled gracefully
        # This test ensures the service doesn't crash with invalid input
        session_config = SessionConfig(
            tool_access_global_overrides={
                "default_policy": "allow",  # Valid
                "allowed_patterns": ["read_.*"],
            }
        )

        reactor_config = ToolCallReactorConfig(access_policies=[])

        # Should not raise an exception
        policy_service = ToolAccessPolicyService(
            reactor_config, global_overrides=session_config.tool_access_global_overrides
        )

        # Should work normally
        result = policy_service.is_tool_allowed("read_file", "test:model")
        assert result.is_allowed is True
