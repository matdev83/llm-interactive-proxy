"""Unit tests for ToolSchemaResolver service.

Tests cover tool schema resolution, collision handling, and format normalization.
"""

from __future__ import annotations

import pytest
from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.connectors.openai_codex.contracts import (
    CodexRequestContext,
    CodexToolSchema,
)
from src.connectors.openai_codex.interfaces import IToolSchemaResolver
from src.connectors.openai_codex.tool_schema import ToolSchemaResolver
from src.core.domain.chat import CanonicalChatRequest, ChatMessage


class TestToolSchemaResolver:
    """Test ToolSchemaResolver service implementation."""

    @pytest.fixture
    def default_tools_provider(self):
        """Create a mock default tools provider."""
        return lambda: [
            {
                "name": "shell",
                "type": "function",
                "description": "Runs a shell command",
                "parameters": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                },
            },
            {
                "name": "read_file",
                "type": "function",
                "description": "Reads a file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
        ]

    @pytest.fixture
    def default_settings(self):
        """Create default settings."""
        from src.connectors.openai_codex.settings import SettingsLoader
        from src.core.config.app_config import AppConfig

        loader = SettingsLoader()
        app_config = AppConfig()
        return loader.load(app_config)

    @pytest.fixture
    def resolver(self, default_settings, default_tools_provider):
        """Create a ToolSchemaResolver instance for testing."""
        return ToolSchemaResolver(
            settings=default_settings, default_tools_provider=default_tools_provider
        )

    @pytest.fixture
    def request_context(self):
        """Create a minimal request context."""
        request = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test")],
        )
        return CodexRequestContext(
            request=request,
            processed_messages=[],
            effective_model="gpt-5.1-codex",
            capabilities=CodexClientCapabilities(),
            session_id="test-session",
        )

    def test_resolver_implements_interface(self, resolver):
        """Verify resolver implements IToolSchemaResolver interface."""
        assert isinstance(resolver, IToolSchemaResolver)

    def test_resolve_tool_schema_codex_default_mode(self, resolver, request_context):
        """Test resolving tool schema in codex_default mode."""
        request_context.capabilities = request_context.capabilities.merge(
            {"tool_schema_mode": "codex_default"}
        )
        result = resolver.resolve_tool_schema(request_context)

        assert isinstance(result, list)
        assert len(result) == 2  # Default tools
        assert all(isinstance(tool, CodexToolSchema) for tool in result)
        assert any(tool.name == "shell" for tool in result)
        assert any(tool.name == "read_file" for tool in result)

    def test_resolve_tool_schema_custom_only_mode(self, resolver, request_context):
        """Test resolving tool schema in custom_only mode."""
        # Create new request with custom tools
        request_with_tools = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test")],
            tools=[
                {
                    "type": "function",
                    "function": {"name": "custom_tool", "description": "Custom tool"},
                }
            ],
        )
        request_context.request = request_with_tools
        request_context.capabilities = request_context.capabilities.merge(
            {"tool_schema_mode": "custom_only"}
        )
        result = resolver.resolve_tool_schema(request_context)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].name == "custom_tool"
        assert result[0].description == "Custom tool"

    def test_resolve_tool_schema_merge_custom_mode(self, resolver, request_context):
        """Test resolving tool schema in merge_custom mode."""
        # Create new request with custom tool that doesn't collide
        request_with_tools = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test")],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "custom_tool",
                        "description": "Custom tool",
                        "parameters": {"type": "object"},
                    },
                }
            ],
        )
        request_context.request = request_with_tools
        request_context.capabilities = request_context.capabilities.merge(
            {"tool_schema_mode": "merge_custom"}
        )
        result = resolver.resolve_tool_schema(request_context)

        assert isinstance(result, list)
        # Should have default tools + custom tool
        assert len(result) >= 3
        tool_names = {tool.name for tool in result}
        assert "shell" in tool_names
        assert "read_file" in tool_names
        assert "custom_tool" in tool_names

    def test_resolve_tool_schema_collision_detection(self, resolver, request_context):
        """Test collision detection when tool has same name but different parameters."""
        # Create new request with custom tool with same name as default but different parameters
        request_with_tools = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test")],
            tools=[
                {
                    "name": "shell",
                    "type": "function",
                    "description": "Custom shell",
                    "parameters": {
                        "type": "object",
                        "properties": {"different": {"type": "string"}},
                    },
                }
            ],
        )
        request_context.request = request_with_tools
        request_context.capabilities = request_context.capabilities.merge(
            {"tool_schema_mode": "merge_custom"}
        )
        result = resolver.resolve_tool_schema(request_context)

        # Should keep default, skip custom due to collision
        shell_tools = [t for t in result if t.name == "shell"]
        assert len(shell_tools) == 1
        # Should be the default one (not the custom one)
        assert shell_tools[0].description == "Runs a shell command"

    def test_resolve_tool_schema_no_collision_same_params(
        self, resolver, request_context
    ):
        """Test that tools with same name and same parameters merge correctly."""
        # Create new request with custom tool with same name and same parameters as default
        request_with_tools = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test")],
            tools=[
                {
                    "name": "shell",
                    "type": "function",
                    "description": "Updated shell description",
                    "parameters": {
                        "type": "object",
                        "properties": {"command": {"type": "string"}},
                    },
                }
            ],
        )
        request_context.request = request_with_tools
        request_context.capabilities = request_context.capabilities.merge(
            {"tool_schema_mode": "merge_custom"}
        )
        result = resolver.resolve_tool_schema(request_context)

        # Should merge (custom overwrites default when params match)
        shell_tools = [t for t in result if t.name == "shell"]
        assert len(shell_tools) == 1
        # Custom description should be used
        assert shell_tools[0].description == "Updated shell description"

    def test_resolve_tool_schema_custom_tool_schema_defaults(
        self, resolver, request_context
    ):
        """Test that custom tool schema defaults from settings are merged."""
        # Update settings to include custom tool schema defaults
        resolver._settings.tool_schema["custom_tools"] = [
            {
                "name": "config_tool",
                "type": "function",
                "description": "Config tool from settings",
                "parameters": {"type": "object"},
            }
        ]
        request_context.capabilities = request_context.capabilities.merge(
            {"tool_schema_mode": "custom_only"}
        )
        result = resolver.resolve_tool_schema(request_context)

        # Should include custom tool from settings
        tool_names = {tool.name for tool in result}
        assert "config_tool" in tool_names

    def test_resolve_tool_schema_openai_format_normalization(
        self, resolver, request_context
    ):
        """Test normalization of OpenAI format tools to Codex format."""
        # Create new request with OpenAI format (function nested)
        request_with_tools = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test")],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "openai_tool",
                        "description": "OpenAI format tool",
                        "parameters": {"type": "object"},
                    },
                }
            ],
        )
        request_context.request = request_with_tools
        request_context.capabilities = request_context.capabilities.merge(
            {"tool_schema_mode": "custom_only"}
        )
        result = resolver.resolve_tool_schema(request_context)

        assert len(result) == 1
        assert result[0].name == "openai_tool"
        assert result[0].description == "OpenAI format tool"

    def test_resolve_tool_schema_codex_format(self, resolver, request_context):
        """Test that Codex format tools (top-level name) work correctly."""
        request_with_tools = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test")],
            tools=[
                {
                    "name": "codex_tool",
                    "type": "function",
                    "description": "Codex format tool",
                    "parameters": {"type": "object"},
                }
            ],
        )
        request_context.request = request_with_tools
        request_context.capabilities = request_context.capabilities.merge(
            {"tool_schema_mode": "custom_only"}
        )
        result = resolver.resolve_tool_schema(request_context)

        assert len(result) == 1
        assert result[0].name == "codex_tool"
        assert result[0].description == "Codex format tool"

    def test_resolve_tool_schema_ignores_tools_without_name(
        self, resolver, request_context
    ):
        """Test that tools without valid names are ignored."""
        request_with_tools = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test")],
            tools=[
                {"type": "function", "function": {"description": "No name"}},
                {"type": "function", "function": {}},
                {"name": "valid_tool", "type": "function", "parameters": {}},
            ],
        )
        request_context.request = request_with_tools
        request_context.capabilities = request_context.capabilities.merge(
            {"tool_schema_mode": "custom_only"}
        )
        result = resolver.resolve_tool_schema(request_context)

        # Should only include the valid tool
        assert len(result) == 1
        assert result[0].name == "valid_tool"

    def test_resolve_tool_schema_merge_custom_no_custom_tools(
        self, resolver, request_context
    ):
        """Test merge_custom mode when no custom tools are provided."""
        request_with_tools = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test")],
            tools=[],
        )
        request_context.request = request_with_tools
        request_context.capabilities = request_context.capabilities.merge(
            {"tool_schema_mode": "merge_custom"}
        )
        result = resolver.resolve_tool_schema(request_context)

        # Should return default tools
        assert len(result) == 2
        assert all(isinstance(tool, CodexToolSchema) for tool in result)

    def test_resolve_tool_schema_custom_tools_deduplication(
        self, resolver, request_context
    ):
        """Test that duplicate custom tools are preserved (matching original behavior)."""
        # Create new request with same tool twice
        request_with_tools = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test")],
            tools=[
                {"name": "duplicate", "type": "function", "parameters": {}},
                {"name": "duplicate", "type": "function", "parameters": {}},
            ],
        )
        request_context.request = request_with_tools
        request_context.capabilities = request_context.capabilities.merge(
            {"tool_schema_mode": "custom_only"}
        )
        result = resolver.resolve_tool_schema(request_context)

        # Original behavior: duplicates are preserved (not deduplicated)
        assert len(result) == 2
        assert all(tool.name == "duplicate" for tool in result)

    def test_resolve_tool_schema_collision_logs_warning(
        self, resolver, request_context, caplog
    ):
        """Test that collision detection logs a warning message."""
        import logging

        # Create new request with custom tool with same name but different parameters
        request_with_tools = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test")],
            tools=[
                {
                    "name": "shell",
                    "type": "function",
                    "description": "Custom shell",
                    "parameters": {
                        "type": "object",
                        "properties": {"different": {"type": "string"}},
                    },
                }
            ],
        )
        request_context.request = request_with_tools
        request_context.capabilities = request_context.capabilities.merge(
            {"tool_schema_mode": "merge_custom"}
        )

        with caplog.at_level(logging.WARNING):
            resolver.resolve_tool_schema(request_context)

        # Verify warning was logged
        assert any(
            "Tool schema collision" in record.message and "shell" in record.message
            for record in caplog.records
        )

    def test_resolve_tool_schema_custom_defaults_in_merge_mode(
        self, resolver, request_context
    ):
        """Test that custom tool schema defaults are merged in merge_custom mode."""
        # Update settings to include custom tool schema defaults
        resolver._settings.tool_schema["custom_tools"] = [
            {
                "name": "config_tool",
                "type": "function",
                "description": "Config tool from settings",
                "parameters": {"type": "object"},
            }
        ]
        request_context.capabilities = request_context.capabilities.merge(
            {"tool_schema_mode": "merge_custom"}
        )
        result = resolver.resolve_tool_schema(request_context)

        # Should include both default tools and config tool
        tool_names = {tool.name for tool in result}
        assert "shell" in tool_names
        assert "read_file" in tool_names
        assert "config_tool" in tool_names

    def test_resolve_tool_schema_base_tools_empty_list(
        self, default_settings, request_context
    ):
        """Test that empty base_tools list yields no tools in codex_default mode."""
        # Update settings to have empty base_tools
        default_settings.tool_schema["base_tools"] = []
        resolver = ToolSchemaResolver(settings=default_settings)

        request_context.capabilities = request_context.capabilities.merge(
            {"tool_schema_mode": "codex_default"}
        )
        result = resolver.resolve_tool_schema(request_context)

        # Should return no tools
        assert isinstance(result, list)
        assert len(result) == 0

    def test_resolve_tool_schema_base_tools_custom_list(
        self, default_settings, request_context
    ):
        """Test that custom base_tools list replaces built-ins."""
        # Update settings to have custom base_tools
        default_settings.tool_schema["base_tools"] = [
            {
                "name": "custom_base_tool",
                "type": "function",
                "description": "Custom base tool",
                "parameters": {
                    "type": "object",
                    "properties": {"arg": {"type": "string"}},
                },
            }
        ]
        resolver = ToolSchemaResolver(settings=default_settings)

        request_context.capabilities = request_context.capabilities.merge(
            {"tool_schema_mode": "codex_default"}
        )
        result = resolver.resolve_tool_schema(request_context)

        # Should return only the custom base tool
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].name == "custom_base_tool"
        assert result[0].description == "Custom base tool"

    def test_resolve_tool_schema_base_tools_merge_custom_mode(
        self, default_settings, request_context
    ):
        """Test that merge_custom mode merges base_tools + request tools."""
        # Update settings to have custom base_tools
        default_settings.tool_schema["base_tools"] = [
            {
                "name": "base_tool_1",
                "type": "function",
                "description": "Base tool 1",
                "parameters": {"type": "object"},
            },
            {
                "name": "base_tool_2",
                "type": "function",
                "description": "Base tool 2",
                "parameters": {"type": "object"},
            },
        ]
        resolver = ToolSchemaResolver(settings=default_settings)

        # Create request with custom tool
        request_with_tools = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test")],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "request_tool",
                        "description": "Request tool",
                        "parameters": {"type": "object"},
                    },
                }
            ],
        )
        request_context.request = request_with_tools
        request_context.capabilities = request_context.capabilities.merge(
            {"tool_schema_mode": "merge_custom"}
        )
        result = resolver.resolve_tool_schema(request_context)

        # Should include both base tools and request tool
        tool_names = {tool.name for tool in result}
        assert "base_tool_1" in tool_names
        assert "base_tool_2" in tool_names
        assert "request_tool" in tool_names
        assert len(result) == 3

    def test_resolve_tool_schema_base_tools_none_falls_back(
        self, default_settings, request_context
    ):
        """Test that base_tools=None falls back to hardcoded built-ins."""
        # Ensure base_tools is None (default)
        default_settings.tool_schema["base_tools"] = None
        resolver = ToolSchemaResolver(settings=default_settings)

        request_context.capabilities = request_context.capabilities.merge(
            {"tool_schema_mode": "codex_default"}
        )
        result = resolver.resolve_tool_schema(request_context)

        # Should return built-in tools (at least shell, apply_patch, view_image)
        assert isinstance(result, list)
        assert len(result) > 0
        tool_names = {tool.name for tool in result}
        # Check for some expected built-ins
        assert any(
            name in tool_names for name in ["shell", "apply_patch", "view_image"]
        )
