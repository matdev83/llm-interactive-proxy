"""Unit tests for PromptResolver service.

Tests cover prompt resolution, instruction merging, and sanitization.
"""

from __future__ import annotations

import pytest
from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.connectors.openai_codex.interfaces import IPromptResolver
from src.connectors.openai_codex.prompt import PromptResolver
from src.connectors.openai_codex.settings import SettingsLoader
from src.core.config.app_config import AppConfig


class TestPromptResolver:
    """Test PromptResolver service implementation."""

    @pytest.fixture
    def resolver(self):
        """Create a PromptResolver instance for testing."""
        return PromptResolver()

    @pytest.fixture
    def default_settings(self):
        """Create default settings."""
        loader = SettingsLoader()
        app_config = AppConfig()
        return loader.load(app_config)

    @pytest.fixture
    def capabilities(self):
        """Create test capabilities."""
        return CodexClientCapabilities()

    def test_resolver_implements_interface(self, resolver):
        """Verify resolver implements IPromptResolver interface."""
        assert isinstance(resolver, IPromptResolver)

    def test_resolve_system_prompt_default_mode(
        self, resolver, default_settings, capabilities
    ):
        """Test resolving system prompt in codex_default mode."""
        caps = capabilities.merge({"prompt_mode": "codex_default"})
        prompt = resolver.resolve_system_prompt(default_settings, caps)

        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_resolve_system_prompt_with_template(self, resolver, capabilities):
        """Test resolving system prompt with custom template."""
        loader = SettingsLoader()
        app_config = AppConfig()
        settings = loader.load(app_config)
        # Override prompt template
        settings.prompt["template"] = "Custom template"
        caps = capabilities.merge({"prompt_mode": "codex_default"})
        prompt = resolver.resolve_system_prompt(settings, caps)

        assert "Custom template" in prompt

    def test_resolve_system_prompt_merge_custom_mode(
        self, resolver, default_settings, capabilities
    ):
        """Test resolving system prompt in merge_custom mode."""
        caps = capabilities.merge({"prompt_mode": "merge_custom"})
        prompt = resolver.resolve_system_prompt(default_settings, caps)

        assert isinstance(prompt, str)

    def test_resolve_system_prompt_custom_only_mode(
        self, resolver, default_settings, capabilities
    ):
        """Test resolving system prompt in custom_only mode."""
        caps = capabilities.merge({"prompt_mode": "custom_only"})
        prompt = resolver.resolve_system_prompt(default_settings, caps)

        assert isinstance(prompt, str)

    def test_resolve_instructions_with_user_instructions(
        self, resolver, default_settings
    ):
        """Test resolving instructions with user-provided instructions."""
        user_instructions = "Custom user instructions"
        result = resolver.resolve_instructions(default_settings, user_instructions)

        assert result is not None
        assert "Custom user instructions" in result
        assert "<user_instructions>" in result

    def test_resolve_instructions_without_user_instructions(
        self, resolver, default_settings
    ):
        """Test resolving instructions without user-provided instructions."""
        result = resolver.resolve_instructions(default_settings, None)

        assert result is None

    def test_resolve_instructions_sanitizes_special_chars(
        self, resolver, default_settings
    ):
        """Test that instructions are sanitized for Codex API."""
        user_instructions = "Test with em dash — and ellipsis …"
        result = resolver.resolve_instructions(default_settings, user_instructions)

        assert result is not None
        # Special characters should be replaced
        assert "—" not in result or "--" in result
