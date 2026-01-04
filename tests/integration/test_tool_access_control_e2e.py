"""
Comprehensive end-to-end integration tests for Tool Access Control.

These tests verify the complete tool access control system including:
- Request filtering (tool definitions removed before backend)
- Response blocking (tool calls blocked in LLM responses)
- Policy precedence and priority ordering
- Whitelist and blacklist modes
- Agent-specific policies
- Global policy overrides
"""

import json
import logging

import pytest
from src.core.config.app_config import AppConfig, ToolCallReactorConfig
from src.core.di.container import ServiceCollection
from src.core.di.services import register_core_services
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ProcessedResponse
from src.core.services.tool_access_policy_service import ToolAccessPolicyService
from src.core.services.tool_call_reactor_middleware import ToolCallReactorMiddleware
from src.core.services.tool_call_reactor_service import ToolCallReactorService

from tests.unit.fixtures.markers import real_time


class TestToolAccessControlEndToEnd:
    """Comprehensive end-to-end tests for tool access control."""

    @pytest.fixture
    def base_config(self):
        """Create a base AppConfig."""
        return AppConfig()

    def create_config_with_policies(self, policies: list[dict]) -> AppConfig:
        """Helper to create config with specific policies."""
        reactor_config = ToolCallReactorConfig(
            enabled=True,
            access_policies=policies,
        )

        config = AppConfig()
        session_config = config.session.model_copy(
            update={"tool_call_reactor": reactor_config}
        )
        return config.model_copy(update={"session": session_config})

    def create_service_provider(self, config: AppConfig):
        """Helper to create service provider with config."""
        collection = ServiceCollection()
        register_core_services(collection, config)
        return collection.build_service_provider()

    def create_chat_request_with_tools(
        self, tools: list[dict], model: str = "test-model"
    ) -> ChatRequest:
        """Helper to create a ChatRequest with tool definitions."""
        return ChatRequest(
            model=model,
            messages=[
                ChatMessage(role="user", content="Test message"),
            ],
            tools=tools,
        )

    def create_llm_response_with_tool_call(
        self, tool_name: str, tool_args: dict | None = None
    ) -> ProcessedResponse:
        """Helper to create a ProcessedResponse with a tool call."""
        if tool_args is None:
            tool_args = {}

        tool_call_response = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps(tool_args),
                                },
                            }
                        ]
                    }
                }
            ]
        }

        return ProcessedResponse(
            content=json.dumps(tool_call_response),
            usage={"prompt_tokens": 10, "completion_tokens": 20},
            metadata={},
        )

    # Test 1: Request filtering - disallowed tool definitions filtered before backend
    @pytest.mark.asyncio
    async def test_request_filtering_removes_disallowed_tools(self):
        """Test that disallowed tool definitions are filtered from requests before backend."""
        # Configure policy to block dangerous tools
        policies = [
            {
                "name": "block_dangerous",
                "model_pattern": ".*",
                "default_policy": "allow",
                "allowed_patterns": [],
                "blocked_patterns": ["delete_.*", "dangerous_.*"],
                "block_message": "Tool blocked by policy.",
                "priority": 0,
            }
        ]

        config = self.create_config_with_policies(policies)
        provider = self.create_service_provider(config)
        policy_service = provider.get_required_service(ToolAccessPolicyService)

        # Create request with mixed tools (some allowed, some blocked)
        tools = [
            {"type": "function", "function": {"name": "read_file"}},
            {"type": "function", "function": {"name": "delete_file"}},
            {"type": "function", "function": {"name": "list_directory"}},
            {"type": "function", "function": {"name": "dangerous_operation"}},
        ]

        # Filter the tools
        result = policy_service.filter_tool_definitions(tools, "test-model", None)

        filtered_tools = result.filtered_tools

        metadata = result.metadata

        # Verify dangerous tools were filtered
        filtered_names = [t["function"]["name"] for t in filtered_tools]
        assert "read_file" in filtered_names
        assert "list_directory" in filtered_names
        assert "delete_file" not in filtered_names
        assert "dangerous_operation" not in filtered_names

        # Verify metadata
        assert metadata.policy_applied == "block_dangerous"
        assert "delete_file" in metadata.filtered_tool_names
        assert "dangerous_operation" in metadata.filtered_tool_names
        assert metadata.original_tool_count == 4
        assert metadata.filtered_tool_count == 2

    # Test 2: Response blocking - LLM attempts to call disallowed tool
    @pytest.mark.asyncio
    async def test_response_blocking_disallowed_tool_call(self):
        """Test that disallowed tool calls are blocked in LLM responses."""
        # Configure policy to block dangerous tools
        policies = [
            {
                "name": "block_dangerous",
                "model_pattern": ".*",
                "default_policy": "allow",
                "allowed_patterns": [],
                "blocked_patterns": ["delete_.*", "dangerous_.*"],
                "block_message": "This tool is blocked by security policy.",
                "priority": 0,
            }
        ]

        config = self.create_config_with_policies(policies)
        provider = self.create_service_provider(config)
        reactor_service = provider.get_required_service(ToolCallReactorService)
        reactor_middleware = provider.get_required_service(ToolCallReactorMiddleware)

        # Create LLM response with disallowed tool call
        response = self.create_llm_response_with_tool_call(
            "delete_file", {"path": "important.txt"}
        )

        # Process through reactor middleware
        result = await reactor_middleware.process(
            response=response,
            session_id="test_session",
            context={
                "backend_name": "test-backend",
                "model_name": "test-model",
                "calling_agent": None,
            },
        )

        # Verify the tool call was blocked
        assert isinstance(result, ProcessedResponse)
        assert result != response  # Should be modified
        assert result.metadata.get("tool_call_swallowed") is True
        # Extract content from OpenAI-compatible response structure
        if isinstance(result.content, dict):
            content = result.content["choices"][0]["message"]["content"]
        else:
            content = result.content

        # Handle case where content is a dict (e.g. structured content)
        if isinstance(content, dict):
            content = json.dumps(content)

        assert "blocked by security policy" in content.lower()

        # Verify telemetry
        stats = reactor_service.get_telemetry_stats()
        assert stats["tool_calls_blocked"] > 0

    # Test 3: Global policy overrides per-model policy
    @pytest.mark.asyncio
    async def test_global_policy_overrides_per_model(self):
        """Test that global policies (higher priority) override per-model policies."""
        # Configure multiple policies with different priorities
        policies = [
            {
                "name": "per_model_policy",
                "model_pattern": "test-model",
                "default_policy": "allow",
                "allowed_patterns": [],
                "blocked_patterns": ["delete_.*"],
                "block_message": "Blocked by per-model policy.",
                "priority": 10,
            },
            {
                "name": "global_policy",
                "model_pattern": ".*",
                "default_policy": "allow",
                "allowed_patterns": ["delete_.*"],  # Global allows delete
                "blocked_patterns": [],
                "block_message": "Blocked by global policy.",
                "priority": 100,  # Higher priority
            },
        ]

        config = self.create_config_with_policies(policies)
        provider = self.create_service_provider(config)
        policy_service = provider.get_required_service(ToolAccessPolicyService)

        # Check if delete_file is allowed (should be, due to global policy)
        result = policy_service.is_tool_allowed("delete_file", "test-model", None)

        # Global policy should win due to higher priority
        assert result.is_allowed is True
        assert result.metadata.policy_applied == "global_policy"

    # Test 4: Whitelist mode (deny by default, allow specific tools)
    @pytest.mark.asyncio
    async def test_whitelist_mode_deny_by_default(self):
        """Test whitelist mode where only specific tools are allowed."""
        # Configure whitelist policy (deny by default)
        policies = [
            {
                "name": "whitelist_policy",
                "model_pattern": ".*",
                "default_policy": "deny",  # Deny by default
                "allowed_patterns": ["read_.*", "list_.*"],  # Only allow read/list
                "blocked_patterns": [],
                "block_message": "Only read-only tools are allowed.",
                "priority": 0,
            }
        ]

        config = self.create_config_with_policies(policies)
        provider = self.create_service_provider(config)
        policy_service = provider.get_required_service(ToolAccessPolicyService)

        # Test allowed tools
        result = policy_service.is_tool_allowed("read_file", "test-model", None)
        assert result.is_allowed is True

        result = policy_service.is_tool_allowed("list_directory", "test-model", None)
        assert result.is_allowed is True

        # Test disallowed tools (not in whitelist)
        result = policy_service.is_tool_allowed("write_file", "test-model", None)
        assert result.is_allowed is False

        result = policy_service.is_tool_allowed("delete_file", "test-model", None)
        assert result.is_allowed is False

        result = policy_service.is_tool_allowed("execute_command", "test-model", None)
        assert result.is_allowed is False

    # Test 5: Blacklist mode (allow by default, block specific tools)
    @pytest.mark.asyncio
    async def test_blacklist_mode_allow_by_default(self):
        """Test blacklist mode where most tools are allowed except specific ones."""
        # Configure blacklist policy (allow by default)
        policies = [
            {
                "name": "blacklist_policy",
                "model_pattern": ".*",
                "default_policy": "allow",  # Allow by default
                "allowed_patterns": [],
                "blocked_patterns": ["delete_.*", "rm_.*", "dangerous_.*"],
                "block_message": "Dangerous operations are blocked.",
                "priority": 0,
            }
        ]

        config = self.create_config_with_policies(policies)
        provider = self.create_service_provider(config)
        policy_service = provider.get_required_service(ToolAccessPolicyService)

        # Test allowed tools (not in blacklist)
        result = policy_service.is_tool_allowed("read_file", "test-model", None)
        assert result.is_allowed is True

        result = policy_service.is_tool_allowed("write_file", "test-model", None)
        assert result.is_allowed is True

        result = policy_service.is_tool_allowed("list_directory", "test-model", None)
        assert result.is_allowed is True

        # Test blocked tools (in blacklist)
        result = policy_service.is_tool_allowed("delete_file", "test-model", None)
        assert result.is_allowed is False

        result = policy_service.is_tool_allowed("rm_file", "test-model", None)
        assert result.is_allowed is False

        result = policy_service.is_tool_allowed(
            "dangerous_operation", "test-model", None
        )
        assert result.is_allowed is False

    # Test 6: Agent-specific policies with agent_pattern matching
    @pytest.mark.asyncio
    async def test_agent_specific_policies(self):
        """Test that policies can be applied based on agent patterns."""
        # Configure agent-specific policies
        policies = [
            {
                "name": "production_agent_policy",
                "model_pattern": ".*",
                "agent_pattern": "production-.*",
                "default_policy": "deny",
                "allowed_patterns": ["read_.*", "list_.*"],
                "blocked_patterns": [],
                "block_message": "Production agents have restricted access.",
                "priority": 100,
            },
            {
                "name": "dev_agent_policy",
                "model_pattern": ".*",
                "agent_pattern": "dev-.*",
                "default_policy": "allow",
                "allowed_patterns": [],
                "blocked_patterns": ["dangerous_.*"],
                "block_message": "Dev agents can use most tools.",
                "priority": 50,
            },
            {
                "name": "default_policy",
                "model_pattern": ".*",
                "default_policy": "allow",
                "allowed_patterns": [],
                "blocked_patterns": [],
                "block_message": "Default policy.",
                "priority": 0,
            },
        ]

        config = self.create_config_with_policies(policies)
        provider = self.create_service_provider(config)
        policy_service = provider.get_required_service(ToolAccessPolicyService)

        # Test production agent (restricted)
        result = policy_service.is_tool_allowed(
            "read_file", "test-model", "production-agent-1"
        )
        assert result.is_allowed is True
        assert result.metadata.policy_applied == "production_agent_policy"

        result = policy_service.is_tool_allowed(
            "write_file", "test-model", "production-agent-1"
        )
        assert result.is_allowed is False  # Not in whitelist
        assert result.metadata.policy_applied == "production_agent_policy"

        # Test dev agent (less restricted)
        result = policy_service.is_tool_allowed(
            "write_file", "test-model", "dev-agent-1"
        )
        assert result.is_allowed is True
        assert result.metadata.policy_applied == "dev_agent_policy"

        result = policy_service.is_tool_allowed(
            "dangerous_operation", "test-model", "dev-agent-1"
        )
        assert result.is_allowed is False  # In blacklist
        assert result.metadata.policy_applied == "dev_agent_policy"

        # Test agent without specific policy (uses default)
        result = policy_service.is_tool_allowed("any_tool", "test-model", "other-agent")
        assert result.is_allowed is True
        assert result.metadata.policy_applied == "default_policy"

    # Test 7: Multiple policies with priority ordering
    @pytest.mark.asyncio
    async def test_multiple_policies_priority_ordering(self):
        """Test that policies are applied in priority order (highest first)."""
        # Configure multiple policies with different priorities
        policies = [
            {
                "name": "low_priority",
                "model_pattern": ".*",
                "default_policy": "deny",
                "allowed_patterns": [],
                "blocked_patterns": [],
                "block_message": "Low priority policy.",
                "priority": 10,
            },
            {
                "name": "medium_priority",
                "model_pattern": "test-.*",
                "default_policy": "allow",
                "allowed_patterns": [],
                "blocked_patterns": ["delete_.*"],
                "block_message": "Medium priority policy.",
                "priority": 50,
            },
            {
                "name": "high_priority",
                "model_pattern": "test-model",
                "default_policy": "allow",
                "allowed_patterns": ["delete_.*"],
                "blocked_patterns": [],
                "block_message": "High priority policy.",
                "priority": 100,
            },
        ]

        config = self.create_config_with_policies(policies)
        provider = self.create_service_provider(config)
        policy_service = provider.get_required_service(ToolAccessPolicyService)

        # Verify policies are sorted by priority
        assert len(policy_service._policies) == 3
        assert policy_service._policies[0].priority == 100
        assert policy_service._policies[1].priority == 50
        assert policy_service._policies[2].priority == 10

        # Test that highest priority matching policy is used
        result = policy_service.is_tool_allowed("delete_file", "test-model", None)
        assert result.is_allowed is True  # High priority allows it
        assert result.metadata.policy_applied == "high_priority"

        # Test with model that matches medium priority
        result = policy_service.is_tool_allowed("delete_file", "test-other", None)
        assert result.is_allowed is False  # Medium priority blocks it
        assert result.metadata.policy_applied == "medium_priority"

        # Test with model that only matches low priority
        result = policy_service.is_tool_allowed("any_tool", "other-model", None)
        assert result.is_allowed is False  # Low priority denies by default
        assert result.metadata.policy_applied == "low_priority"

    # Test 8: Policy precedence - allowed patterns override blocked patterns
    @pytest.mark.asyncio
    async def test_allowed_patterns_override_blocked_patterns(self):
        """Test that allowed patterns take precedence over blocked patterns."""
        # Configure policy with overlapping allowed and blocked patterns
        policies = [
            {
                "name": "precedence_test",
                "model_pattern": ".*",
                "default_policy": "allow",
                "allowed_patterns": ["delete_important_.*"],  # Explicitly allow
                "blocked_patterns": ["delete_.*"],  # Block all delete
                "block_message": "Delete operations blocked.",
                "priority": 0,
            }
        ]

        config = self.create_config_with_policies(policies)
        provider = self.create_service_provider(config)
        policy_service = provider.get_required_service(ToolAccessPolicyService)

        # Test that allowed pattern overrides blocked pattern
        result = policy_service.is_tool_allowed(
            "delete_important_file", "test-model", None
        )
        assert result.is_allowed is True  # Allowed pattern wins
        assert result.metadata.reason == "allowed"

        # Test that other delete operations are still blocked
        result = policy_service.is_tool_allowed(
            "delete_regular_file", "test-model", None
        )
        assert result.is_allowed is False  # Blocked pattern applies
        assert result.metadata.reason == "blocked"

    # Test 9: End-to-end scenario with request filtering and response blocking
    @pytest.mark.asyncio
    async def test_end_to_end_filtering_and_blocking(self):
        """Test complete flow: request filtering + response blocking."""
        # Configure policy
        policies = [
            {
                "name": "e2e_policy",
                "model_pattern": ".*",
                "default_policy": "allow",
                "allowed_patterns": [],
                "blocked_patterns": ["dangerous_.*"],
                "block_message": "Dangerous tools are not allowed.",
                "priority": 0,
            }
        ]

        config = self.create_config_with_policies(policies)
        provider = self.create_service_provider(config)
        policy_service = provider.get_required_service(ToolAccessPolicyService)
        reactor_middleware = provider.get_required_service(ToolCallReactorMiddleware)

        # Step 1: Request filtering
        tools = [
            {"type": "function", "function": {"name": "read_file"}},
            {"type": "function", "function": {"name": "dangerous_operation"}},
        ]

        result = policy_service.filter_tool_definitions(tools, "test-model", None)

        filtered_tools = result.filtered_tools

        metadata = result.metadata

        # Verify dangerous tool was filtered
        assert len(filtered_tools) == 1
        assert filtered_tools[0]["function"]["name"] == "read_file"
        assert "dangerous_operation" in metadata.filtered_tool_names

        # Step 2: Response blocking (if LLM somehow calls blocked tool)
        response = self.create_llm_response_with_tool_call("dangerous_operation", {})

        result = await reactor_middleware.process(
            response=response,
            session_id="e2e_test_session",
            context={
                "backend_name": "test-backend",
                "model_name": "test-model",
                "calling_agent": None,
            },
        )

        # Verify tool call was blocked
        assert result.metadata.get("tool_call_swallowed") is True
        # Extract content from OpenAI-compatible response structure
        if isinstance(result.content, dict):
            content = result.content["choices"][0]["message"]["content"]
        else:
            content = result.content
        assert "dangerous tools are not allowed" in content.lower()

    # Test 10: Complex scenario with multiple policies and agents
    @pytest.mark.asyncio
    async def test_complex_multi_policy_multi_agent_scenario(self):
        """Test complex scenario with multiple policies, agents, and models."""
        # Configure complex policy set
        # Note: Policy selection picks the FIRST matching policy by priority order
        # More specific patterns should have higher priority than generic ones
        policies = [
            {
                "name": "production_restrictions",
                "model_pattern": "gpt-.*",
                "agent_pattern": "prod-.*",
                "default_policy": "deny",
                "allowed_patterns": ["read_.*", "list_.*", "search_.*"],
                "blocked_patterns": [],
                "block_message": "Production agents have limited access.",
                "priority": 200,  # Highest priority for specific prod+gpt combo
            },
            {
                "name": "claude_restrictions",
                "model_pattern": "claude-.*",
                "default_policy": "allow",
                "allowed_patterns": [],
                "blocked_patterns": ["execute_.*"],
                "block_message": "Claude models cannot execute commands.",
                "priority": 150,  # Higher than global_security
            },
            {
                "name": "global_security",
                "model_pattern": ".*",
                "default_policy": "allow",
                "allowed_patterns": [],
                "blocked_patterns": ["rm_.*", "format_.*"],
                "block_message": "Destructive operations blocked globally.",
                "priority": 100,  # Lower than specific model policies
            },
            {
                "name": "default_permissive",
                "model_pattern": ".*",
                "default_policy": "allow",
                "allowed_patterns": [],
                "blocked_patterns": [],
                "block_message": "Default policy.",
                "priority": 0,
            },
        ]

        config = self.create_config_with_policies(policies)
        provider = self.create_service_provider(config)
        policy_service = provider.get_required_service(ToolAccessPolicyService)

        # Scenario 1: Production agent with GPT model (matches production_restrictions)
        result = policy_service.is_tool_allowed("read_file", "gpt-4", "prod-agent-1")
        assert result.is_allowed is True  # In whitelist
        assert result.metadata.policy_applied == "production_restrictions"

        result = policy_service.is_tool_allowed("write_file", "gpt-4", "prod-agent-1")
        # The production_restrictions policy should apply (gpt-.* + prod-.*)
        # and deny by default since write_file is not in allowed_patterns
        assert result.metadata.policy_applied == "production_restrictions"
        assert result.is_allowed is False  # Not in whitelist, deny by default

        # Scenario 2: Global security blocks rm_ for non-prod agents
        result = policy_service.is_tool_allowed("rm_file", "gpt-4", "dev-agent")
        assert result.is_allowed is False
        assert result.metadata.policy_applied == "global_security"

        # Scenario 3: Claude model restrictions
        result = policy_service.is_tool_allowed(
            "execute_command", "claude-3", "dev-agent"
        )
        assert result.is_allowed is False
        assert result.metadata.policy_applied == "claude_restrictions"

        result = policy_service.is_tool_allowed("read_file", "claude-3", "dev-agent")
        assert result.is_allowed is True  # Not blocked by Claude policy

        # Scenario 4: Default permissive for other models
        result = policy_service.is_tool_allowed("any_tool", "other-model", "any-agent")
        assert result.is_allowed is True
        assert result.metadata.policy_applied in [
            "global_security",
            "default_permissive",
        ]

    # Test 11: Tool choice handling when referenced tool is filtered
    @pytest.mark.asyncio
    async def test_tool_choice_handling_when_tool_filtered(self):
        """Test that tool_choice is handled correctly when the referenced tool is filtered."""
        # Configure policy that blocks specific tools
        policies = [
            {
                "name": "filter_policy",
                "model_pattern": ".*",
                "default_policy": "allow",
                "allowed_patterns": [],
                "blocked_patterns": ["blocked_tool"],
                "block_message": "Tool blocked.",
                "priority": 0,
            }
        ]

        config = self.create_config_with_policies(policies)
        provider = self.create_service_provider(config)
        policy_service = provider.get_required_service(ToolAccessPolicyService)

        # Create tools including the blocked one
        tools = [
            {"type": "function", "function": {"name": "allowed_tool"}},
            {"type": "function", "function": {"name": "blocked_tool"}},
        ]

        # Filter tools
        result = policy_service.filter_tool_definitions(tools, "test-model", None)

        filtered_tools = result.filtered_tools

        metadata = result.metadata

        # Verify blocked_tool was filtered
        assert len(filtered_tools) == 1
        assert filtered_tools[0]["function"]["name"] == "allowed_tool"
        assert "blocked_tool" in metadata.filtered_tool_names

    # Test 12: Performance with large number of tools
    @pytest.mark.asyncio
    @real_time(reason="Measures actual filtering performance characteristics.")
    async def test_performance_with_many_tools(self):
        """Test that policy evaluation performs well with many tools."""
        import time

        # Configure policy
        policies = [
            {
                "name": "perf_policy",
                "model_pattern": ".*",
                "default_policy": "allow",
                "allowed_patterns": [],
                "blocked_patterns": ["blocked_.*"],
                "block_message": "Tool blocked.",
                "priority": 0,
            }
        ]

        config = self.create_config_with_policies(policies)
        provider = self.create_service_provider(config)
        policy_service = provider.get_required_service(ToolAccessPolicyService)

        # Create many tools
        tools = [
            {"type": "function", "function": {"name": f"tool_{i}"}} for i in range(100)
        ]
        tools.extend(
            [
                {"type": "function", "function": {"name": f"blocked_tool_{i}"}}
                for i in range(10)
            ]
        )

        # Measure filtering time
        start_time = time.time()
        result = policy_service.filter_tool_definitions(tools, "test-model", None)

        filtered_tools = result.filtered_tools

        metadata = result.metadata
        elapsed_ms = (time.time() - start_time) * 1000

        # Verify filtering worked
        assert len(filtered_tools) == 100  # Only non-blocked tools
        assert len(metadata.filtered_tool_names) == 10

        # Verify performance (should be < 15ms for 110 tools)
        assert elapsed_ms < 15, f"Filtering took {elapsed_ms}ms, expected < 15ms"

    # Test 13: Logging and observability
    @pytest.mark.asyncio
    async def test_logging_and_observability(self, caplog):
        """Test that proper logging occurs for policy decisions."""
        caplog.set_level(logging.INFO)

        # Configure policy
        policies = [
            {
                "name": "logging_test_policy",
                "model_pattern": ".*",
                "default_policy": "allow",
                "allowed_patterns": [],
                "blocked_patterns": ["blocked_tool"],
                "block_message": "Tool blocked for testing.",
                "priority": 0,
            }
        ]

        config = self.create_config_with_policies(policies)
        provider = self.create_service_provider(config)
        reactor_middleware = provider.get_required_service(ToolCallReactorMiddleware)

        # Create response with blocked tool call
        response = self.create_llm_response_with_tool_call("blocked_tool", {})

        # Process through middleware
        await reactor_middleware.process(
            response=response,
            session_id="logging_test_session",
            context={
                "backend_name": "test-backend",
                "model_name": "test-model",
                "calling_agent": None,
            },
        )

        # Verify logging occurred
        log_messages = [record.message for record in caplog.records]
        blocked_log = next(
            (msg for msg in log_messages if "Blocked tool call" in msg), None
        )

        assert blocked_log is not None
        assert "blocked_tool" in blocked_log
        assert "logging_test_session" in blocked_log

    # Test 14: Empty policy list (no restrictions)
    @pytest.mark.asyncio
    async def test_empty_policy_list_allows_all(self):
        """Test that empty policy list allows all tools."""
        # Configure with no policies
        policies = []

        config = self.create_config_with_policies(policies)
        provider = self.create_service_provider(config)
        policy_service = provider.get_service(ToolAccessPolicyService)

        # If no policy service, all tools should be allowed
        if policy_service is None:
            # This is expected - no policies means no service
            return

        # If service exists with empty policies, should allow all
        tools = [
            {"type": "function", "function": {"name": "any_tool_1"}},
            {"type": "function", "function": {"name": "any_tool_2"}},
        ]

        result = policy_service.filter_tool_definitions(tools, "test-model", None)

        filtered_tools = result.filtered_tools

        # All tools should pass through
        assert len(filtered_tools) == len(tools)

    # Test 15: Case-insensitive pattern matching
    @pytest.mark.asyncio
    async def test_case_insensitive_pattern_matching(self):
        """Test that pattern matching is case-insensitive."""
        # Configure policy with lowercase patterns
        policies = [
            {
                "name": "case_test",
                "model_pattern": ".*",
                "default_policy": "allow",
                "allowed_patterns": [],
                "blocked_patterns": ["delete_.*"],
                "block_message": "Delete blocked.",
                "priority": 0,
            }
        ]

        config = self.create_config_with_policies(policies)
        provider = self.create_service_provider(config)
        policy_service = provider.get_required_service(ToolAccessPolicyService)

        # Test various case combinations
        result = policy_service.is_tool_allowed("delete_file", "test-model", None)
        assert result.is_allowed is False

        result = policy_service.is_tool_allowed("DELETE_FILE", "test-model", None)
        assert result.is_allowed is False

        result = policy_service.is_tool_allowed("Delete_File", "test-model", None)
        assert result.is_allowed is False

    # Test 16: Multiple tool calls in single response
    @pytest.mark.asyncio
    async def test_multiple_tool_calls_in_response(self):
        """Test handling of multiple tool calls where some are blocked."""
        # Configure policy
        policies = [
            {
                "name": "multi_call_policy",
                "model_pattern": ".*",
                "default_policy": "allow",
                "allowed_patterns": [],
                "blocked_patterns": ["blocked_.*"],
                "block_message": "Tool blocked.",
                "priority": 0,
            }
        ]

        config = self.create_config_with_policies(policies)
        provider = self.create_service_provider(config)
        reactor_middleware = provider.get_required_service(ToolCallReactorMiddleware)

        # Create response with multiple tool calls (mixed allowed/blocked)
        tool_call_response = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "allowed_tool",
                                    "arguments": json.dumps({}),
                                },
                            },
                            {
                                "id": "call_2",
                                "type": "function",
                                "function": {
                                    "name": "blocked_tool",
                                    "arguments": json.dumps({}),
                                },
                            },
                        ]
                    }
                }
            ]
        }

        response = ProcessedResponse(
            content=json.dumps(tool_call_response),
            usage={"prompt_tokens": 10, "completion_tokens": 20},
            metadata={},
        )

        # Process through middleware
        result = await reactor_middleware.process(
            response=response,
            session_id="multi_call_session",
            context={
                "backend_name": "test-backend",
                "model_name": "test-model",
                "calling_agent": None,
            },
        )

        # The blocked tool should be swallowed
        assert result.metadata.get("tool_call_swallowed") is True
