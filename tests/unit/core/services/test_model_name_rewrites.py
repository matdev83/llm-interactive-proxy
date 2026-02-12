"""Unit tests for model name rewrites feature.

Tests ModelAliasResolver and BackendModelResolver integration.
"""

from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from src.core.config.app_config import AppConfig, BackendSettings, ModelAliasRule
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.interfaces.backend_lifecycle_manager_interface import (
    IBackendLifecycleManager,
)
from src.core.interfaces.planning_phase_manager_interface import IPlanningPhaseManager
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.backend_model_resolver import BackendModelResolver
from src.core.services.model_alias_resolver import ModelAliasResolver


class TestModelAliasResolver:
    """Test cases for ModelAliasResolver."""

    @pytest.fixture
    def base_config(self):
        """Base configuration without model aliases."""
        return AppConfig(
            backends=BackendSettings(default_backend="openai"), model_aliases=[]
        )

    @pytest.fixture
    def config_with_aliases(self):
        """Configuration with model alias rules."""
        return AppConfig(
            backends=BackendSettings(default_backend="openai"),
            model_aliases=[
                ModelAliasRule(
                    pattern="^claude-3-sonnet-20240229$",
                    replacement="gemini-oauth-plan:gemini-1.5-flash",
                ),
                ModelAliasRule(
                    pattern="^gpt-(.*)", replacement="openrouter:openai/gpt-\\1"
                ),
                ModelAliasRule(
                    pattern="^(.*)$",
                    replacement="gemini-oauth-plan:gemini-1.5-pro",
                ),
            ],
        )

    def test_apply_model_aliases_no_rules(self, base_config):
        """Test that model name is unchanged when no alias rules are configured."""
        resolver = ModelAliasResolver(config=base_config)
        original_model = "gpt-4"
        result = resolver.resolve(original_model)
        assert result == original_model

    def test_apply_model_aliases_static_replacement(self, config_with_aliases):
        """Test static model name replacement."""
        resolver = ModelAliasResolver(config=config_with_aliases)
        original_model = "claude-3-sonnet-20240229"
        expected_model = "gemini-oauth-plan:gemini-1.5-flash"

        result = resolver.resolve(original_model)
        assert result == expected_model

    def test_apply_model_aliases_regex_with_capture_groups(self, config_with_aliases):
        """Test regex replacement with capture groups."""
        resolver = ModelAliasResolver(config=config_with_aliases)
        original_model = "gpt-4-turbo"
        expected_model = "openrouter:openai/gpt-4-turbo"

        result = resolver.resolve(original_model)
        assert result == expected_model

    def test_apply_model_aliases_first_match_wins(self):
        """Test that only the first matching rule is applied."""
        config = AppConfig(
            backends=BackendSettings(default_backend="openai"),
            model_aliases=[
                ModelAliasRule(pattern="gpt-.*", replacement="first-match:gpt-model"),
                ModelAliasRule(pattern="gpt-4", replacement="second-match:gpt-4"),
                ModelAliasRule(pattern="^(.*)$", replacement="catch-all:model"),
            ],
        )
        resolver = ModelAliasResolver(config=config)

        original_model = "gpt-4"
        expected_model = "first-match:gpt-model"

        result = resolver.resolve(original_model)
        assert result == expected_model

    def test_apply_model_aliases_no_match(self):
        """Test that model name is unchanged when no rules match."""
        config = AppConfig(
            backends=BackendSettings(default_backend="openai"),
            model_aliases=[
                ModelAliasRule(
                    pattern="^claude-.*", replacement="gemini:claude-replacement"
                ),
                ModelAliasRule(
                    pattern="^gpt-.*", replacement="openrouter:gpt-replacement"
                ),
            ],
        )
        resolver = ModelAliasResolver(config=config)

        original_model = "llama-2-70b"
        result = resolver.resolve(original_model)
        assert result == original_model

    def test_apply_model_aliases_invalid_regex(self, caplog):
        """Test handling of invalid regex patterns."""
        config = AppConfig(
            backends=BackendSettings(default_backend="openai"),
            model_aliases=[
                ModelAliasRule(
                    pattern="[invalid-regex",  # Missing closing bracket
                    replacement="should-not-be-used",
                ),
                ModelAliasRule(pattern="gpt-.*", replacement="openrouter:gpt-model"),
            ],
        )
        resolver = ModelAliasResolver(config=config)

        original_model = "gpt-4"
        expected_model = "openrouter:gpt-model"

        with caplog.at_level("WARNING"):
            result = resolver.resolve(original_model)

        assert result == expected_model
        assert "Invalid regex pattern" in caplog.text

    def test_apply_model_aliases_regex_substring_match(self):
        """Test that regex rules can match anywhere in the model string."""
        config = AppConfig(
            backends=BackendSettings(default_backend="openai"),
            model_aliases=[
                ModelAliasRule(pattern=".*turbo$", replacement="suffix:matched"),
            ],
        )
        resolver = ModelAliasResolver(config=config)

        original_model = "gpt-4-turbo"
        result = resolver.resolve(original_model)

        assert result == "suffix:matched"

    def test_complex_regex_patterns(self):
        """Test complex regex patterns with multiple capture groups."""
        config = AppConfig(
            backends=BackendSettings(default_backend="openai"),
            model_aliases=[
                ModelAliasRule(
                    pattern="^(gpt|claude)-(\\d+)-(\\w+)$",
                    replacement="unified:\\1-\\2-\\3-model",
                )
            ],
        )
        resolver = ModelAliasResolver(config=config)

        # Test GPT model
        result = resolver.resolve("gpt-4-turbo")
        assert result == "unified:gpt-4-turbo-model"

        # Test Claude model
        result = resolver.resolve("claude-3-sonnet")
        assert result == "unified:claude-3-sonnet-model"

        # Test non-matching model
        result = resolver.resolve("llama-2-70b")
        assert result == "llama-2-70b"


class TestBackendModelResolverIntegration:
    """Test BackendModelResolver integration with ModelAliasResolver."""

    @pytest.fixture
    def config_with_aliases(self):
        """Configuration with model alias rules."""
        return AppConfig(
            backends=BackendSettings(default_backend="openai"),
            model_aliases=[
                ModelAliasRule(
                    pattern="^gpt-(.*)", replacement="openrouter:openai/gpt-\\1"
                ),
            ],
        )

    @pytest.mark.asyncio
    async def test_resolve_target_with_aliases(self, config_with_aliases):
        """Test that model aliases are applied during backend resolution."""
        session_service = Mock(spec=ISessionService)
        session_service.get_session = AsyncMock(return_value=None)

        backend_lifecycle = Mock(spec=IBackendLifecycleManager)
        backend_lifecycle.get_disabled_backends = Mock(return_value={})

        planning_phase = Mock(spec=IPlanningPhaseManager)
        planning_phase.apply_if_needed = AsyncMock()

        model_alias_resolver = ModelAliasResolver(config=config_with_aliases)
        routing_service = Mock()
        routing_service.resolve_model_only_backend = Mock(return_value="openrouter")
        routing_service.resolve_backend_instance = Mock(
            side_effect=lambda backend, model, excluded_backends=None: backend
        )

        resolver = BackendModelResolver(
            session_service=session_service,
            model_alias_resolver=model_alias_resolver,
            planning_phase_manager=planning_phase,
            backend_lifecycle_manager=backend_lifecycle,
            config=config_with_aliases,
            routing_service=routing_service,  # type: ignore[arg-type]
        )

        request = ChatRequest(
            model="gpt-4-turbo", messages=[ChatMessage(role="user", content="Hello")]
        )

        target = await resolver.resolve_target(request)

        # The model should be rewritten by the alias rule
        assert (
            target.model == "openai/gpt-4-turbo"
        )  # After parsing backend:model format
        assert target.backend == "openrouter"
        assert target.uri_params == {}

    @pytest.mark.asyncio
    async def test_resolve_target_static_route_precedence(self):
        """Test that static_route takes precedence over model aliases."""
        config = AppConfig(
            backends=BackendSettings(
                default_backend="openai",
                static_route="forced-backend:forced-model",
            ),
            model_aliases=[
                ModelAliasRule(pattern=".*", replacement="should-not-be-used:model")
            ],
        )

        session_service = Mock(spec=ISessionService)
        session_service.get_session = AsyncMock(return_value=None)

        backend_lifecycle = Mock(spec=IBackendLifecycleManager)
        backend_lifecycle.get_disabled_backends = Mock(return_value={})

        planning_phase = Mock(spec=IPlanningPhaseManager)
        planning_phase.apply_if_needed = AsyncMock()

        model_alias_resolver = ModelAliasResolver(config=config)
        routing_service = Mock()
        routing_service.resolve_model_only_backend = Mock(return_value="forced-backend")
        routing_service.resolve_backend_instance = Mock(
            side_effect=lambda backend, model, excluded_backends=None: backend
        )

        resolver = BackendModelResolver(
            session_service=session_service,
            model_alias_resolver=model_alias_resolver,
            planning_phase_manager=planning_phase,
            backend_lifecycle_manager=backend_lifecycle,
            config=config,
            routing_service=routing_service,  # type: ignore[arg-type]
        )

        request = ChatRequest(
            model="any-model", messages=[ChatMessage(role="user", content="Hello")]
        )

        target = await resolver.resolve_target(request)

        # Static route should override alias rules
        assert target.backend == "forced-backend"
        assert target.model == "forced-model"
        assert target.uri_params == {}


class TestModelAliasesConfiguration:
    """Test cases for model aliases configuration from different sources."""

    def test_cli_parameter_support(self):
        """Test that CLI parameters are properly parsed and validated."""
        from src.core.cli import parse_cli_args

        # Test valid CLI arguments
        args = parse_cli_args(
            [
                "--model-alias",
                "^gpt-(.*)=openrouter:openai/gpt-\\1",
                "--model-alias",
                "^claude-(.*)=anthropic:claude-\\1",
            ]
        )

        assert hasattr(args, "model_aliases")
        assert args.model_aliases is not None
        assert len(args.model_aliases) == 2
        assert args.model_aliases[0] == ("^gpt-(.*)", "openrouter:openai/gpt-\\1")
        assert args.model_aliases[1] == ("^claude-(.*)", "anthropic:claude-\\1")

    def test_cli_parameter_validation_invalid_format(self):
        """Test that invalid CLI parameter format raises error."""
        from src.core.cli import parse_cli_args

        with pytest.raises(SystemExit):  # argparse raises SystemExit on error
            parse_cli_args(["--model-alias", "invalid-format-no-equals"])

    def test_cli_parameter_validation_invalid_regex(self):
        """Test that invalid regex pattern raises error."""
        from src.core.cli import parse_cli_args

        with pytest.raises(SystemExit):  # argparse raises SystemExit on error
            parse_cli_args(["--model-alias", "[invalid-regex=replacement"])

    def test_environment_variable_support(self):
        """Test that environment variables are properly loaded."""
        import json
        import os

        from src.core.config.app_config import AppConfig

        # Set environment variable
        alias_data = [
            {"pattern": "^gpt-(.*)", "replacement": "openrouter:openai/gpt-\\1"},
            {"pattern": "^claude-(.*)", "replacement": "anthropic:claude-\\1"},
        ]
        os.environ["MODEL_ALIASES"] = json.dumps(alias_data)

        try:
            config = AppConfig.from_env()
            assert len(config.model_aliases) == 2
            assert config.model_aliases[0].pattern == "^gpt-(.*)"
            assert config.model_aliases[0].replacement == "openrouter:openai/gpt-\\1"
            assert config.model_aliases[1].pattern == "^claude-(.*)"
            assert config.model_aliases[1].replacement == "anthropic:claude-\\1"
        finally:
            # Clean up
            if "MODEL_ALIASES" in os.environ:
                del os.environ["MODEL_ALIASES"]

    def test_environment_variable_invalid_json(self, caplog):
        """Test that invalid JSON in environment variable is handled gracefully."""
        import os

        from src.core.config.app_config import AppConfig

        # Set invalid JSON
        os.environ["MODEL_ALIASES"] = "invalid-json"

        try:
            config = AppConfig.from_env()
            assert config.model_aliases == []
            assert "Invalid MODEL_ALIASES environment variable format" in caplog.text
        finally:
            # Clean up
            if "MODEL_ALIASES" in os.environ:
                del os.environ["MODEL_ALIASES"]

    def test_cli_overrides_config_file(self):
        """Test that CLI parameters override config file settings."""
        from src.core.cli import apply_cli_args, parse_cli_args
        from src.core.config.app_config import (
            AppConfig,
            BackendSettings,
            ModelAliasRule,
        )

        # Create config with file-based aliases
        config = AppConfig(
            backends=BackendSettings(default_backend="openai"),
            model_aliases=[
                ModelAliasRule(pattern="^file-pattern$", replacement="file-replacement")
            ],
        )

        # Parse CLI arguments that will override the config file
        args = parse_cli_args(["--model-alias", "^cli-pattern$=cli-replacement"])

        # Mock the load_config function to return our test config
        import src.core.cli

        original_load_config = src.core.cli.load_config

        def _load_config_override(
            path: str | None = None,
            resolution: Any | None = None,
        ) -> AppConfig:
            _ = path
            _ = resolution
            return cast(AppConfig, config)

        src.core.cli.load_config = _load_config_override

        try:
            # apply_cli_args returns a tuple of (AppConfig, ParameterResolution)
            result_config, _ = apply_cli_args(args, return_resolution=True)

            # CLI should override config file
            assert len(result_config.model_aliases) == 1
            assert result_config.model_aliases[0].pattern == "^cli-pattern$"
            assert result_config.model_aliases[0].replacement == "cli-replacement"
        finally:
            # Restore original function
            src.core.cli.load_config = original_load_config

    @pytest.fixture(autouse=True)
    def clean_environment(self):
        """Ensure clean environment for each test."""
        import os

        # Store original values
        original_env = {}
        env_vars_to_clean = ["COMMAND_PREFIX", "MODEL_ALIASES"]

        for var in env_vars_to_clean:
            original_env[var] = os.environ.get(var)
            if var in os.environ:
                del os.environ[var]

        yield

        # Restore original values
        for var, value in original_env.items():
            if value is not None:
                os.environ[var] = value
            elif var in os.environ:
                del os.environ[var]

    def test_precedence_order_cli_env_config(self):
        """Test the complete precedence order: CLI > ENV > Config File."""
        import json
        import os
        import tempfile
        from pathlib import Path

        import yaml
        from src.core.cli import apply_cli_args, parse_cli_args
        from src.core.config.app_config import load_config

        # Store original environment state and ensure clean environment
        original_command_prefix = os.environ.get("COMMAND_PREFIX")
        original_model_aliases = os.environ.get("MODEL_ALIASES")

        # Clear any existing environment variables that might interfere
        if "COMMAND_PREFIX" in os.environ:
            del os.environ["COMMAND_PREFIX"]
        if "MODEL_ALIASES" in os.environ:
            del os.environ["MODEL_ALIASES"]

        # 1. Create temporary config file (lowest precedence)
        config_data = {
            "backends": {"default_backend": "openai"},
            "model_aliases": [
                {"pattern": "^config-pattern$", "replacement": "config-replacement"}
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            config_path = f.name

        # 2. Set environment variable (middle precedence)
        env_alias_data = [
            {"pattern": "^env-pattern$", "replacement": "env-replacement"}
        ]
        os.environ["MODEL_ALIASES"] = json.dumps(env_alias_data)

        # 3. Define CLI arguments (highest precedence)
        cli_args = parse_cli_args(
            [
                "--config",
                config_path,
                "--model-alias",
                "^cli-pattern$=cli-replacement",
            ]
        )

        try:
            # Load config from file, which will also pick up env vars
            load_config(config_path)

            # Now, apply CLI args, which should override both file and env
            final_config, _ = apply_cli_args(cli_args, return_resolution=True)

            # Assert that CLI arguments have the highest precedence
            assert len(final_config.model_aliases) == 1
            assert final_config.model_aliases[0].pattern == "^cli-pattern$"
            assert final_config.model_aliases[0].replacement == "cli-replacement"

        finally:
            # Clean up
            Path(config_path).unlink()

            # Restore original environment state
            if original_model_aliases is not None:
                os.environ["MODEL_ALIASES"] = original_model_aliases
            elif "MODEL_ALIASES" in os.environ:
                del os.environ["MODEL_ALIASES"]

            if original_command_prefix is not None:
                os.environ["COMMAND_PREFIX"] = original_command_prefix
            elif "COMMAND_PREFIX" in os.environ:
                del os.environ["COMMAND_PREFIX"]
