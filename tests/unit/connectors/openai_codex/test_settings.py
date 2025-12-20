"""Unit tests for SettingsLoader service.

Tests cover configuration normalization, precedence order, and edge cases.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.connectors.openai_codex.interfaces import ISettingsLoader
from src.connectors.openai_codex.settings import SettingsLoader
from src.core.config.app_config import AppConfig, BackendConfig, BackendSettings


class TestSettingsLoader:
    """Test SettingsLoader service implementation."""

    @pytest.fixture
    def loader(self):
        """Create a SettingsLoader instance for testing."""
        return SettingsLoader()

    @pytest.fixture
    def app_config(self):
        """Create a basic app config for testing."""
        config = AppConfig()
        if not hasattr(config, "backends"):
            config.backends = BackendSettings()
        return config

    def test_loader_implements_interface(self, loader):
        """Verify loader implements ISettingsLoader interface."""
        assert isinstance(loader, ISettingsLoader)

    def test_load_defaults(self, loader, app_config):
        """Test loading settings with default values."""
        settings = loader.load(app_config)

        assert settings.default_capabilities == CodexClientCapabilities()
        assert settings.agent_overrides == {}
        assert settings.renderer["default"] == "none"
        assert settings.renderer["fallback"] == "summary"
        assert settings.prompt["template"] is None
        assert settings.prompt["deduplicate"] is True
        assert settings.prompt["fallback_to_default"] is True
        assert settings.tool_schema["base_tools"] is None
        assert settings.tool_schema["custom_tools"] == []
        assert settings.streaming["max_retries"] == 2
        assert settings.streaming["retry_backoff_seconds"] == (0.5, 1.5, 3.0)
        assert settings.compatibility_layer["enabled"] is False

    def test_load_from_yaml_config(self, loader, app_config):
        """Test loading settings from YAML backend config."""
        # Create backend config with codex extra
        backend_config = BackendConfig(
            extra={
                "codex": {
                    "renderer": {"default": "custom_renderer"},
                    "prompt": {"template": "custom_template"},
                    "streaming": {"max_retries": 5},
                }
            }
        )
        app_config.backends.__dict__["openai_codex"] = backend_config

        settings = loader.load(app_config)

        assert settings.renderer["default"] == "custom_renderer"
        assert settings.prompt["template"] == "custom_template"
        assert settings.streaming["max_retries"] == 5

    def test_load_from_env_vars(self, loader, app_config):
        """Test loading settings from environment variables."""
        with patch.dict(
            os.environ,
            {
                "OPENAI_CODEX_RENDERER_DEFAULT": "env_renderer",
                "OPENAI_CODEX_PROMPT_TEMPLATE": "env_template",
                "OPENAI_CODEX_STREAMING_MAX_RETRIES": "10",
            },
        ):
            settings = loader.load(app_config)

            assert settings.renderer["default"] == "env_renderer"
            assert settings.prompt["template"] == "env_template"
            assert settings.streaming["max_retries"] == 10

    def test_env_overrides_yaml(self, loader, app_config):
        """Test that environment variables override YAML config."""
        backend_config = BackendConfig(
            extra={
                "codex": {
                    "renderer": {"default": "yaml_renderer"},
                }
            }
        )
        app_config.backends.__dict__["openai_codex"] = backend_config

        with patch.dict(os.environ, {"OPENAI_CODEX_RENDERER_DEFAULT": "env_renderer"}):
            settings = loader.load(app_config)

            assert settings.renderer["default"] == "env_renderer"

    def test_load_default_capabilities_from_json_env(self, loader, app_config):
        """Test loading default capabilities from JSON environment variable."""
        json_caps = '{"tool_text_format": "json_format", "protocol": "codex"}'
        with patch.dict(os.environ, {"OPENAI_CODEX_DEFAULT_CAPABILITIES": json_caps}):
            settings = loader.load(app_config)

            assert settings.default_capabilities.tool_text_format == "json_format"
            assert settings.default_capabilities.protocol == "codex"

    def test_load_agent_overrides(self, loader, app_config):
        """Test loading agent capability overrides."""
        backend_config = BackendConfig(
            extra={
                "codex": {
                    "agent_capabilities": {
                        "kilocode": {"tool_text_format": "kilo_format"},
                        "droid": {"protocol": "openai"},
                    }
                }
            }
        )
        app_config.backends.__dict__["openai_codex"] = backend_config

        settings = loader.load(app_config)

        assert "kilocode" in settings.agent_overrides
        assert settings.agent_overrides["kilocode"]["tool_text_format"] == "kilo_format"
        assert "droid" in settings.agent_overrides
        assert settings.agent_overrides["droid"]["protocol"] == "openai"

    def test_load_tool_schema(self, loader, app_config):
        """Test loading tool schema configuration."""
        backend_config = BackendConfig(
            extra={
                "codex": {
                    "tool_schema": {
                        "base_tools": [{"name": "base_tool", "type": "function"}],
                        "custom_tools": [{"name": "custom_tool", "type": "function"}],
                    }
                }
            }
        )
        app_config.backends.__dict__["openai_codex"] = backend_config

        settings = loader.load(app_config)

        assert len(settings.tool_schema["base_tools"]) == 1
        assert settings.tool_schema["base_tools"][0]["name"] == "base_tool"
        assert len(settings.tool_schema["custom_tools"]) == 1
        assert settings.tool_schema["custom_tools"][0]["name"] == "custom_tool"

    def test_load_compatibility_layer_settings(self, loader, app_config):
        """Test loading compatibility layer settings."""
        backend_config = BackendConfig(
            extra={
                "codex": {
                    "compatibility_layer": {
                        "enabled": True,
                        "detection": {
                            "cache_ttl_seconds": 7200,
                            "heuristic_threshold": 3,
                        },
                        "translation": {"max_tool_execution_timeout": 60},
                    }
                }
            }
        )
        app_config.backends.__dict__["openai_codex"] = backend_config

        settings = loader.load(app_config)

        assert settings.compatibility_layer["enabled"] is True
        assert settings.compatibility_layer["detection"]["cache_ttl_seconds"] == 7200
        assert settings.compatibility_layer["detection"]["heuristic_threshold"] == 3
        assert (
            settings.compatibility_layer["translation"]["max_tool_execution_timeout"]
            == 60
        )

    def test_invalid_json_env_ignored(self, loader, app_config):
        """Test that invalid JSON in environment variables is ignored."""
        with patch.dict(
            os.environ, {"OPENAI_CODEX_DEFAULT_CAPABILITIES": "invalid json"}
        ):
            settings = loader.load(app_config)
            # Should fall back to defaults
            assert settings.default_capabilities == CodexClientCapabilities()

    def test_invalid_tool_schema_filtered(self, loader, app_config):
        """Test that invalid tool schemas are filtered out."""
        backend_config = BackendConfig(
            extra={
                "codex": {
                    "tool_schema": {
                        "custom_tools": [
                            {"name": "valid_tool", "type": "function"},
                            {"type": "function"},  # Missing name
                            {"name": ""},  # Empty name
                            "not_a_dict",  # Not a dict
                        ]
                    }
                }
            }
        )
        app_config.backends.__dict__["openai_codex"] = backend_config

        settings = loader.load(app_config)

        # Only valid tool should be included
        assert len(settings.tool_schema["custom_tools"]) == 1
        assert settings.tool_schema["custom_tools"][0]["name"] == "valid_tool"

    def test_prompt_deduplicate_env_override(self, loader, app_config):
        """Test prompt deduplicate setting from environment variable."""
        backend_config = BackendConfig(
            extra={"codex": {"prompt": {"deduplicate": False}}}
        )
        app_config.backends.__dict__["openai_codex"] = backend_config

        with patch.dict(os.environ, {"OPENAI_CODEX_PROMPT_DEDUPLICATE": "true"}):
            settings = loader.load(app_config)
            assert settings.prompt["deduplicate"] is True

    def test_renderer_registry_configuration(self, loader, app_config):
        """Test that renderer registry is configured correctly."""
        backend_config = BackendConfig(
            extra={
                "codex": {
                    "renderer": {
                        "default": "custom",
                        "aliases": {"alias1": "target1"},
                        "modules": {"module1": "path1"},
                    }
                }
            }
        )
        app_config.backends.__dict__["openai_codex"] = backend_config

        with patch(
            "src.connectors.openai_codex.settings.configure_renderer_registry"
        ) as mock_configure:
            loader.load(app_config)

            mock_configure.assert_called_once()
            call_kwargs = mock_configure.call_args[1]
            assert call_kwargs["default"] == "custom"
            assert call_kwargs["aliases"] == {"alias1": "target1"}
            assert call_kwargs["modules"] == {"module1": "path1"}

    def test_capabilities_merge_with_renderer_default(self, loader, app_config):
        """Test that capabilities are merged with renderer default."""
        backend_config = BackendConfig(
            extra={"codex": {"renderer": {"default": "custom_format"}}}
        )
        app_config.backends.__dict__["openai_codex"] = backend_config

        settings = loader.load(app_config)

        # If default_capabilities.tool_text_format is None or "none",
        # it should be set to renderer default
        if settings.default_capabilities.tool_text_format in {None, "none"}:
            # This is handled in the loader logic
            assert settings.default_capabilities.tool_text_format == "custom_format"
