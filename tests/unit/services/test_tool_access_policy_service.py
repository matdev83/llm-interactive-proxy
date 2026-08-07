"""Unit tests for ToolAccessPolicyService."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from src.core.config.app_config import ToolCallReactorConfig
from src.core.services.tool_access_policy_service import (
    AccessPolicy,
    ToolAccessPolicyService,
)


class TestAccessPolicy:
    """Tests for AccessPolicy dataclass."""

    def test_compile_patterns_valid(self) -> None:
        """Test compiling valid regex patterns."""
        policy = AccessPolicy(
            name="test_policy",
            model_pattern="gpt-.*",
            agent_pattern="agent-.*",
            allowed_patterns=["read_.*", "list_.*"],
            blocked_patterns=["delete_.*", "rm_.*"],
            default_policy="allow",
        )

        policy.compile_patterns()

        assert policy._model_regex is not None
        assert policy._agent_regex is not None
        assert len(policy._allowed_regexes) == 2
        assert len(policy._blocked_regexes) == 2

    def test_compile_patterns_invalid_model_pattern(self) -> None:
        """Test handling of invalid model pattern."""
        policy = AccessPolicy(
            name="test_policy",
            model_pattern="[invalid",  # Invalid regex
            default_policy="allow",
        )

        policy.compile_patterns()

        assert policy._model_regex is None

    def test_compile_patterns_invalid_allowed_pattern(self) -> None:
        """Test handling of invalid allowed pattern."""
        policy = AccessPolicy(
            name="test_policy",
            model_pattern=".*",
            allowed_patterns=["valid_.*", "[invalid"],
            default_policy="allow",
        )

        policy.compile_patterns()

        # Should compile valid pattern, skip invalid
        assert len(policy._allowed_regexes) == 1

    def test_matches_context_model_only(self) -> None:
        """Test context matching with model pattern only."""
        policy = AccessPolicy(
            name="test_policy",
            model_pattern="gpt-4.*",
            default_policy="allow",
        )
        policy.compile_patterns()

        assert policy.matches_context("gpt-4-turbo")
        assert policy.matches_context("gpt-4o")
        assert not policy.matches_context("gpt-3.5-turbo")
        assert not policy.matches_context("claude-3")

    def test_matches_context_case_insensitive(self) -> None:
        """Test case-insensitive pattern matching."""
        policy = AccessPolicy(
            name="test_policy",
            model_pattern="GPT-4.*",
            default_policy="allow",
        )
        policy.compile_patterns()

        assert policy.matches_context("gpt-4-turbo")
        assert policy.matches_context("GPT-4-TURBO")
        assert policy.matches_context("Gpt-4-Turbo")

    def test_matches_context_with_agent(self) -> None:
        """Test context matching with both model and agent patterns."""
        policy = AccessPolicy(
            name="test_policy",
            model_pattern=".*",
            agent_pattern="production-.*",
            default_policy="allow",
        )
        policy.compile_patterns()

        assert policy.matches_context("gpt-4", "production-agent")
        assert policy.matches_context("claude-3", "production-bot")
        assert not policy.matches_context("gpt-4", "dev-agent")
        assert not policy.matches_context("gpt-4", None)

    def test_is_tool_allowed_with_allowed_patterns(self) -> None:
        """Test tool allowed by allowed patterns."""
        policy = AccessPolicy(
            name="test_policy",
            model_pattern=".*",
            allowed_patterns=["read_.*", "list_.*"],
            default_policy="deny",
        )
        policy.compile_patterns()

        assert policy.is_tool_allowed("read_file")
        assert policy.is_tool_allowed("list_directory")
        assert not policy.is_tool_allowed("write_file")
        assert not policy.is_tool_allowed("delete_file")

    def test_is_tool_allowed_with_blocked_patterns(self) -> None:
        """Test tool blocked by blocked patterns."""
        policy = AccessPolicy(
            name="test_policy",
            model_pattern=".*",
            blocked_patterns=["delete_.*", "rm_.*"],
            default_policy="allow",
        )
        policy.compile_patterns()

        assert not policy.is_tool_allowed("delete_file")
        assert not policy.is_tool_allowed("rm_directory")
        assert policy.is_tool_allowed("read_file")
        assert policy.is_tool_allowed("write_file")

    def test_is_tool_allowed_precedence(self) -> None:
        """Test that allowed patterns override blocked patterns."""
        policy = AccessPolicy(
            name="test_policy",
            model_pattern=".*",
            allowed_patterns=["read_.*"],
            blocked_patterns=["read_secret"],
            default_policy="deny",
        )
        policy.compile_patterns()

        # Allowed pattern should override blocked pattern
        assert policy.is_tool_allowed("read_secret")
        assert policy.is_tool_allowed("read_file")
        assert not policy.is_tool_allowed("write_file")

    def test_is_tool_allowed_default_allow(self) -> None:
        """Test default allow policy."""
        policy = AccessPolicy(
            name="test_policy",
            model_pattern=".*",
            default_policy="allow",
        )
        policy.compile_patterns()

        assert policy.is_tool_allowed("any_tool")
        assert policy.is_tool_allowed("another_tool")

    def test_is_tool_allowed_default_deny(self) -> None:
        """Test default deny policy."""
        policy = AccessPolicy(
            name="test_policy",
            model_pattern=".*",
            default_policy="deny",
        )
        policy.compile_patterns()

        assert not policy.is_tool_allowed("any_tool")
        assert not policy.is_tool_allowed("another_tool")


class TestToolAccessPolicyService:
    """Tests for ToolAccessPolicyService."""

    def test_init_empty_config(self) -> None:
        """Test initialization with empty configuration."""
        config = ToolCallReactorConfig()
        service = ToolAccessPolicyService(config)

        assert len(service._policies) == 0
        assert service._global_policy is None

    def test_init_with_valid_policies(self) -> None:
        """Test initialization with valid policies."""
        config = ToolCallReactorConfig(
            access_policies=[
                {
                    "name": "policy1",
                    "model_pattern": "gpt-.*",
                    "default_policy": "allow",
                    "blocked_patterns": ["delete_.*"],
                },
                {
                    "name": "policy2",
                    "model_pattern": "claude-.*",
                    "default_policy": "deny",
                    "allowed_patterns": ["read_.*"],
                },
            ]
        )
        service = ToolAccessPolicyService(config)

        assert len(service._policies) == 2
        assert service._policies[0].name in ("policy1", "policy2")

    def test_init_with_invalid_policy_missing_name(self) -> None:
        """Test initialization skips policy missing name."""
        config = ToolCallReactorConfig(
            access_policies=[
                {
                    "model_pattern": "gpt-.*",
                    "default_policy": "allow",
                },
            ]
        )
        service = ToolAccessPolicyService(config)

        assert len(service._policies) == 0

    def test_init_with_invalid_policy_missing_model_pattern(self) -> None:
        """Test initialization skips policy missing model_pattern."""
        config = ToolCallReactorConfig(
            access_policies=[
                {
                    "name": "policy1",
                    "default_policy": "allow",
                },
            ]
        )
        service = ToolAccessPolicyService(config)

        assert len(service._policies) == 0

    def test_init_with_invalid_policy_missing_default_policy(self) -> None:
        """Test initialization skips policy missing default_policy."""
        config = ToolCallReactorConfig(
            access_policies=[
                {
                    "name": "policy1",
                    "model_pattern": "gpt-.*",
                },
            ]
        )
        service = ToolAccessPolicyService(config)

        assert len(service._policies) == 0

    def test_init_with_invalid_default_policy_value(self) -> None:
        """Test initialization skips policy with invalid default_policy value."""
        config = ToolCallReactorConfig(
            access_policies=[
                {
                    "name": "policy1",
                    "model_pattern": "gpt-.*",
                    "default_policy": "invalid",
                },
            ]
        )
        service = ToolAccessPolicyService(config)

        assert len(service._policies) == 0

    def test_init_with_priority_ordering(self) -> None:
        """Test policies are sorted by priority."""
        config = ToolCallReactorConfig(
            access_policies=[
                {
                    "name": "low_priority",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                    "priority": 10,
                },
                {
                    "name": "high_priority",
                    "model_pattern": ".*",
                    "default_policy": "deny",
                    "priority": 100,
                },
                {
                    "name": "medium_priority",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                    "priority": 50,
                },
            ]
        )
        service = ToolAccessPolicyService(config)

        assert len(service._policies) == 3
        assert service._policies[0].name == "high_priority"
        assert service._policies[1].name == "medium_priority"
        assert service._policies[2].name == "low_priority"

    def test_global_overrides(self) -> None:
        """Test global policy overrides."""
        config = ToolCallReactorConfig(
            access_policies=[
                {
                    "name": "base_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                },
            ]
        )
        global_overrides = {
            "allowed_patterns": ["read_.*"],
            "blocked_patterns": ["write_.*"],
            "default_policy": "deny",
        }
        service = ToolAccessPolicyService(config, global_overrides)

        assert service._global_policy is not None
        assert service._global_policy.name == "global_override"
        assert service._global_policy.priority == 1000

    def test_select_policy_no_match(self) -> None:
        """Test policy selection when no policy matches."""
        config = ToolCallReactorConfig(
            access_policies=[
                {
                    "name": "gpt_policy",
                    "model_pattern": "gpt-.*",
                    "default_policy": "allow",
                },
            ]
        )
        service = ToolAccessPolicyService(config)

        policy = service._select_policy("claude-3")
        assert policy is None

    def test_select_policy_single_match(self) -> None:
        """Test policy selection with single matching policy."""
        config = ToolCallReactorConfig(
            access_policies=[
                {
                    "name": "gpt_policy",
                    "model_pattern": "gpt-.*",
                    "default_policy": "allow",
                },
            ]
        )
        service = ToolAccessPolicyService(config)

        policy = service._select_policy("gpt-4")
        assert policy is not None
        assert policy.name == "gpt_policy"

    def test_select_policy_multiple_matches_priority(self) -> None:
        """Test policy selection with multiple matches uses priority."""
        config = ToolCallReactorConfig(
            access_policies=[
                {
                    "name": "general_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                    "priority": 10,
                },
                {
                    "name": "specific_policy",
                    "model_pattern": "gpt-4.*",
                    "default_policy": "deny",
                    "priority": 100,
                },
            ]
        )
        service = ToolAccessPolicyService(config)

        policy = service._select_policy("gpt-4-turbo")
        assert policy is not None
        assert policy.name == "specific_policy"

    def test_select_policy_global_override_precedence(self) -> None:
        """Test global policy takes precedence over all others."""
        config = ToolCallReactorConfig(
            access_policies=[
                {
                    "name": "base_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                    "priority": 100,
                },
            ]
        )
        global_overrides = {
            "default_policy": "deny",
        }
        service = ToolAccessPolicyService(config, global_overrides)

        policy = service._select_policy("any-model")
        assert policy is not None
        assert policy.name == "global_override"

    def test_filter_tool_definitions_no_policy(self) -> None:
        """Test filtering with no matching policy."""
        config = ToolCallReactorConfig()
        service = ToolAccessPolicyService(config)

        tools = [
            {"type": "function", "function": {"name": "read_file"}},
            {"type": "function", "function": {"name": "write_file"}},
        ]

        result = service.filter_tool_definitions(tools, "gpt-4")
        filtered = result.filtered_tools
        metadata = result.metadata

        assert len(filtered) == 2
        assert metadata.policy_applied is None
        assert metadata.original_tool_count == 2
        assert metadata.filtered_tool_count == 2

    def test_filter_tool_definitions_allow_all(self) -> None:
        """Test filtering with allow-all policy."""
        config = ToolCallReactorConfig(
            access_policies=[
                {
                    "name": "allow_all",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                },
            ]
        )
        service = ToolAccessPolicyService(config)

        tools = [
            {"type": "function", "function": {"name": "read_file"}},
            {"type": "function", "function": {"name": "write_file"}},
        ]

        result = service.filter_tool_definitions(tools, "gpt-4")
        filtered = result.filtered_tools
        metadata = result.metadata

        assert len(filtered) == 2
        assert metadata.policy_applied == "allow_all"

    def test_filter_tool_definitions_block_some(self) -> None:
        """Test filtering blocks specific tools."""
        config = ToolCallReactorConfig(
            access_policies=[
                {
                    "name": "block_write",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                    "blocked_patterns": ["write_.*", "delete_.*"],
                },
            ]
        )
        service = ToolAccessPolicyService(config)

        tools = [
            {"type": "function", "function": {"name": "read_file"}},
            {"type": "function", "function": {"name": "write_file"}},
            {"type": "function", "function": {"name": "delete_file"}},
        ]

        result = service.filter_tool_definitions(tools, "gpt-4")
        filtered = result.filtered_tools
        metadata = result.metadata

        assert len(filtered) == 1
        assert filtered[0]["function"]["name"] == "read_file"
        assert metadata.filtered_tool_names == ["write_file", "delete_file"]

    def test_filter_tool_definitions_whitelist_mode(self) -> None:
        """Test filtering in whitelist mode (deny by default)."""
        config = ToolCallReactorConfig(
            access_policies=[
                {
                    "name": "whitelist",
                    "model_pattern": ".*",
                    "default_policy": "deny",
                    "allowed_patterns": ["read_.*", "list_.*"],
                },
            ]
        )
        service = ToolAccessPolicyService(config)

        tools = [
            {"type": "function", "function": {"name": "read_file"}},
            {"type": "function", "function": {"name": "list_directory"}},
            {"type": "function", "function": {"name": "write_file"}},
            {"type": "function", "function": {"name": "execute_command"}},
        ]

        result = service.filter_tool_definitions(tools, "gpt-4")
        filtered = result.filtered_tools

        assert len(filtered) == 2
        tool_names = [t["function"]["name"] for t in filtered]
        assert "read_file" in tool_names
        assert "list_directory" in tool_names

    def test_filter_tool_definitions_anthropic_format(self) -> None:
        """Test filtering with Anthropic tool format."""
        config = ToolCallReactorConfig(
            access_policies=[
                {
                    "name": "block_write",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                    "blocked_patterns": ["write_.*"],
                },
            ]
        )
        service = ToolAccessPolicyService(config)

        tools = [
            {"name": "read_file"},
            {"name": "write_file"},
        ]

        result = service.filter_tool_definitions(tools, "claude-3")
        filtered = result.filtered_tools

        assert len(filtered) == 1
        assert filtered[0]["name"] == "read_file"

    def test_is_tool_allowed_no_policy(self) -> None:
        """Test is_tool_allowed with no matching policy."""
        config = ToolCallReactorConfig()
        service = ToolAccessPolicyService(config)

        result = service.is_tool_allowed("read_file", "gpt-4")
        is_allowed = result.is_allowed
        metadata = result.metadata

        assert is_allowed is True
        assert metadata.policy_applied is None
        assert metadata.reason == "no_policy_matched"

    def test_is_tool_allowed_with_policy(self) -> None:
        """Test is_tool_allowed with matching policy."""
        config = ToolCallReactorConfig(
            access_policies=[
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                    "blocked_patterns": ["delete_.*"],
                },
            ]
        )
        service = ToolAccessPolicyService(config)

        result = service.is_tool_allowed("read_file", "gpt-4")
        is_allowed = result.is_allowed
        metadata = result.metadata
        assert is_allowed is True
        assert metadata.reason == "allowed"

        result = service.is_tool_allowed("delete_file", "gpt-4")
        is_blocked = result.is_allowed
        metadata = result.metadata
        assert is_blocked is False
        assert metadata.reason == "blocked"

    def test_get_block_message_no_policy(self) -> None:
        """Test get_block_message with no matching policy."""
        config = ToolCallReactorConfig()
        service = ToolAccessPolicyService(config)

        message = service.get_block_message("delete_file", "gpt-4")

        assert "not allowed" in message.lower()

    def test_get_block_message_with_policy(self) -> None:
        """Test get_block_message with matching policy."""
        custom_message = "Custom block message for this policy"
        config = ToolCallReactorConfig(
            access_policies=[
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                    "block_message": custom_message,
                },
            ]
        )
        service = ToolAccessPolicyService(config)

        message = service.get_block_message("delete_file", "gpt-4")

        assert message == custom_message

    def test_extract_tool_name_openai_format(self) -> None:
        """Test extracting tool name from OpenAI format."""
        tool = {"type": "function", "function": {"name": "test_tool"}}
        name = ToolAccessPolicyService._extract_tool_name(tool)
        assert name == "test_tool"

    def test_extract_tool_name_anthropic_format(self) -> None:
        """Test extracting tool name from Anthropic format."""
        tool = {"name": "test_tool", "description": "A test tool"}
        name = ToolAccessPolicyService._extract_tool_name(tool)
        assert name == "test_tool"

    def test_extract_tool_name_invalid_format(self) -> None:
        """Test extracting tool name from invalid format."""
        tool = {"invalid": "format"}
        name = ToolAccessPolicyService._extract_tool_name(tool)
        assert name is None

    def test_empty_patterns(self) -> None:
        """Test policy with empty allowed and blocked patterns."""
        config = ToolCallReactorConfig(
            access_policies=[
                {
                    "name": "empty_patterns",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                    "allowed_patterns": [],
                    "blocked_patterns": [],
                },
            ]
        )
        service = ToolAccessPolicyService(config)

        tools = [
            {"type": "function", "function": {"name": "any_tool"}},
        ]

        result = service.filter_tool_definitions(tools, "gpt-4")
        filtered = result.filtered_tools

        # Should allow all tools with default policy
        assert len(filtered) == 1

    def test_malformed_configuration(self) -> None:
        """Test handling of malformed configuration."""
        # Pydantic validates the config before our code sees it,
        # so malformed configs raise ValidationError
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            ToolCallReactorConfig(
                access_policies=[
                    "not_a_dict",  # Invalid: should be dict
                    {
                        "name": "valid_policy",
                        "model_pattern": ".*",
                        "default_policy": "allow",
                    },
                ]
            )

    def test_agent_specific_policy(self) -> None:
        """Test policy with agent pattern matching."""
        config = ToolCallReactorConfig(
            access_policies=[
                {
                    "name": "production_policy",
                    "model_pattern": ".*",
                    "agent_pattern": "production-.*",
                    "default_policy": "deny",
                    "allowed_patterns": ["read_.*"],
                },
                {
                    "name": "dev_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                },
            ]
        )
        service = ToolAccessPolicyService(config)

        # Production agent should use restrictive policy
        result = service.is_tool_allowed("write_file", "gpt-4", "production-agent")
        is_allowed = result.is_allowed
        assert is_allowed is False

        # Dev agent should use permissive policy
        result = service.is_tool_allowed("write_file", "gpt-4", "dev-agent")
        is_allowed = result.is_allowed
        assert is_allowed is True

    def test_precedence_allowed_overrides_blocked(self) -> None:
        """Test that allowed patterns override blocked patterns."""
        config = ToolCallReactorConfig(
            access_policies=[
                {
                    "name": "precedence_test",
                    "model_pattern": ".*",
                    "default_policy": "deny",
                    "allowed_patterns": ["read_.*"],
                    "blocked_patterns": ["read_secret"],
                },
            ]
        )
        service = ToolAccessPolicyService(config)

        # read_secret matches both allowed and blocked, allowed should win
        result = service.is_tool_allowed("read_secret", "gpt-4")
        is_allowed = result.is_allowed
        assert is_allowed is True

    def test_policy_cache_is_thread_safe(self) -> None:
        """Ensure caching logic remains correct under concurrent access."""
        config = ToolCallReactorConfig(
            access_policies=[
                {
                    "name": "cache_test_policy",
                    "model_pattern": "gpt-.*",
                    "default_policy": "deny",
                    "allowed_patterns": ["safe_tool"],
                }
            ]
        )
        service = ToolAccessPolicyService(config)
        tools: list[dict[str, Any]] = [
            {"type": "function", "function": {"name": "safe_tool"}},
            {"type": "function", "function": {"name": "danger_tool"}},
        ]

        models = ["gpt-4"] * 16 + ["claude-3"] * 16
        agents = [f"agent-{i % 4}" for i in range(len(models))]

        def evaluate(model: str, agent: str) -> tuple[int, str | None]:
            result = service.filter_tool_definitions(
                tools=tools,
                model_name=model,
                agent=agent,
            )
            filtered = result.filtered_tools
            metadata = result.metadata
            return len(filtered), metadata.policy_applied

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(evaluate, models, agents))

        permitted_counts = [length for length, _ in results[:16]]
        fallback_counts = [length for length, _ in results[16:]]
        applied_policies = [policy for _, policy in results[:16]]

        # gpt-4 requests should filter out the blocked tool
        assert all(count == 1 for count in permitted_counts)
        assert all(policy == "cache_test_policy" for policy in applied_policies)
        # claude-3 requests should bypass policies entirely
        assert all(count == 2 for count in fallback_counts)

        metrics = service.get_performance_metrics()
        expected_cache_size = len(set(zip(models, agents, strict=False)))
        assert metrics["cache_size"] == expected_cache_size
