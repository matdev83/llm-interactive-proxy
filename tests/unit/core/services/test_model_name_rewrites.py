"""Unit tests for model name rewrites feature."""

from unittest.mock import AsyncMock, Mock

import pytest
from src.core.config.app_config import AppConfig, ModelAliasRule
from src.core.domain.chat import ChatRequest
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.rate_limiter_interface import IRateLimiter
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_service import BackendService


class TestModelNameRewrites:
    """Test cases for model name rewrite functionality."""

    @pytest.fixture
    def mock_factory(self):
        """Mock backend factory."""
        return Mock(spec=BackendFactory)

    @pytest.fixture
    def mock_rate_limiter(self):
        """Mock rate limiter."""
        return Mock(spec=IRateLimiter)

    @pytest.fixture
    def mock_session_service(self):
        """Mock session service."""
        return Mock(spec=ISessionService)

    @pytest.fixture
    def mock_app_state(self):
        """Mock application state."""
        return Mock(spec=IApplicationState)

    @pytest.fixture
    def base_config(self):
        """Base configuration without model aliases."""
        return AppConfig(backends={"default_backend": "openai"}, model_aliases=[])

    @pytest.fixture
    def config_with_aliases(self):
        """Configuration with model alias rules."""
        return AppConfig(
            backends={"default_backend": "openai"},
            model_aliases=[
                ModelAliasRule(
                    pattern="^claude-3-sonnet-20240229$",
                    replacement="gemini-cli-oauth-personal:gemini-1.5-flash",
                ),
                ModelAliasRule(
                    pattern="^gpt-(.*)", replacement="openrouter:openai/gpt-\\1"
                ),
                ModelAliasRule(
                    pattern="^(.*)$",
                    replacement="gemini-cli-oauth-personal:gemini-1.5-pro",
                ),
            ],
        )

    @pytest.fixture
    def backend_service(
        self,
        mock_factory,
        mock_rate_limiter,
        base_config,
        mock_session_service,
        mock_app_state,
    ):
        """Backend service with base configuration."""
        return BackendService(
            factory=mock_factory,
            rate_limiter=mock_rate_limiter,
            config=base_config,
            session_service=mock_session_service,
            app_state=mock_app_state,
        )

    @pytest.fixture
    def backend_service_with_aliases(
        self,
        mock_factory,
        mock_rate_limiter,
        config_with_aliases,
        mock_session_service,
        mock_app_state,
    ):
        """Backend service with model alias configuration."""
        return BackendService(
            factory=mock_factory,
            rate_limiter=mock_rate_limiter,
            config=config_with_aliases,
            session_service=mock_session_service,
            app_state=mock_app_state,
        )

    def test_apply_model_aliases_no_rules(self, backend_service):
        """Test that model name is unchanged when no alias rules are configured."""
        # AC7: Given a request with a model name that does not match any pattern
        # in model_aliases, the model name MUST remain unchanged.
        original_model = "gpt-4"
        result = backend_service._apply_model_aliases(original_model)
        assert result == original_model

    def test_apply_model_aliases_static_replacement(self, backend_service_with_aliases):
        """Test static model name replacement."""
        # AC4: Given a request with a model name that exactly matches a pattern
        # for a static replacement, the model name MUST be rewritten to the
        # corresponding replacement value.
        original_model = "claude-3-sonnet-20240229"
        expected_model = "gemini-cli-oauth-personal:gemini-1.5-flash"

        result = backend_service_with_aliases._apply_model_aliases(original_model)
        assert result == expected_model

    def test_apply_model_aliases_regex_with_capture_groups(
        self, backend_service_with_aliases
    ):
        """Test regex replacement with capture groups."""
        # AC5: Given a request with a model name that matches a regex pattern
        # with capture groups, the model name MUST be rewritten using the
        # replacement string with the captured values correctly substituted.
        original_model = "gpt-4-turbo"
        expected_model = "openrouter:openai/gpt-4-turbo"

        result = backend_service_with_aliases._apply_model_aliases(original_model)
        assert result == expected_model

    def test_apply_model_aliases_first_match_wins(self):
        """Test that only the first matching rule is applied."""
        # AC6: Given multiple rules in model_aliases, if a model name matches
        # more than one pattern, only the first matching rule in the list MUST be applied.
        config = AppConfig(
            backends={"default_backend": "openai"},
            model_aliases=[
                ModelAliasRule(pattern="gpt-.*", replacement="first-match:gpt-model"),
                ModelAliasRule(pattern="gpt-4", replacement="second-match:gpt-4"),
                ModelAliasRule(pattern="^(.*)$", replacement="catch-all:model"),
            ],
        )

        backend_service = BackendService(
            factory=Mock(spec=BackendFactory),
            rate_limiter=Mock(spec=IRateLimiter),
            config=config,
            session_service=Mock(spec=ISessionService),
            app_state=Mock(spec=IApplicationState),
        )

        original_model = "gpt-4"
        expected_model = "first-match:gpt-model"

        result = backend_service._apply_model_aliases(original_model)
        assert result == expected_model

    def test_apply_model_aliases_no_match(self, backend_service_with_aliases):
        """Test that model name is unchanged when no rules match."""
        # Create a config with specific patterns that won't match our test model
        config = AppConfig(
            backends={"default_backend": "openai"},
            model_aliases=[
                ModelAliasRule(
                    pattern="^claude-.*", replacement="gemini:claude-replacement"
                ),
                ModelAliasRule(
                    pattern="^gpt-.*", replacement="openrouter:gpt-replacement"
                ),
            ],
        )

        backend_service = BackendService(
            factory=Mock(spec=BackendFactory),
            rate_limiter=Mock(spec=IRateLimiter),
            config=config,
            session_service=Mock(spec=ISessionService),
            app_state=Mock(spec=IApplicationState),
        )

        original_model = "llama-2-70b"
        result = backend_service._apply_model_aliases(original_model)
        assert result == original_model

    def test_apply_model_aliases_invalid_regex(self, caplog):
        """Test handling of invalid regex patterns."""
        config = AppConfig(
            backends={"default_backend": "openai"},
            model_aliases=[
                ModelAliasRule(
                    pattern="[invalid-regex",  # Missing closing bracket
                    replacement="should-not-be-used",
                ),
                ModelAliasRule(pattern="gpt-.*", replacement="openrouter:gpt-model"),
            ],
        )

        backend_service = BackendService(
            factory=Mock(spec=BackendFactory),
            rate_limiter=Mock(spec=IRateLimiter),
            config=config,
            session_service=Mock(spec=ISessionService),
            app_state=Mock(spec=IApplicationState),
        )

        original_model = "gpt-4"
        expected_model = "openrouter:gpt-model"

        result = backend_service._apply_model_aliases(original_model)
        assert result == expected_model

        # Check that warning was logged for invalid regex
        assert "Invalid regex pattern" in caplog.text

    @pytest.mark.asyncio
    async def test_resolve_backend_and_model_with_aliases(
        self, backend_service_with_aliases
    ):
        """Test that model aliases are applied during backend resolution."""
        # Mock session service to return None (no session)
        backend_service_with_aliases._session_service.get_session = AsyncMock(
            return_value=None
        )

        request = ChatRequest(
            model="gpt-4-turbo", messages=[{"role": "user", "content": "Hello"}]
        )

        backend_type, effective_model = (
            await backend_service_with_aliases._resolve_backend_and_model(request)
        )

        # The model should be rewritten by the alias rule
        assert (
            effective_model == "openai/gpt-4-turbo"
        )  # After parsing backend:model format
        assert backend_type == "openrouter"

    @pytest.mark.asyncio
    async def test_resolve_backend_and_model_static_route_precedence(self):
        """Test that static_route takes precedence over model aliases."""
        # AC8: If the --static-route CLI parameter is set, it MUST take precedence
        # over any model_aliases rules. The model alias logic should not be executed.
        config = AppConfig(
            backends={
                "default_backend": "openai",
                "static_route": "forced-backend:forced-model",
            },
            model_aliases=[
                ModelAliasRule(pattern=".*", replacement="should-not-be-used:model")
            ],
        )

        backend_service = BackendService(
            factory=Mock(spec=BackendFactory),
            rate_limiter=Mock(spec=IRateLimiter),
            config=config,
            session_service=Mock(spec=ISessionService),
            app_state=Mock(spec=IApplicationState),
        )

        # Mock session service
        backend_service._session_service.get_session = AsyncMock(return_value=None)

        request = ChatRequest(
            model="any-model", messages=[{"role": "user", "content": "Hello"}]
        )

        backend_type, effective_model = (
            await backend_service._resolve_backend_and_model(request)
        )

        # Static route should override alias rules
        assert backend_type == "forced-backend"
        assert effective_model == "forced-model"

    def test_config_validation_valid_rules(self):
        """Test that valid model alias rules can be configured."""
        # AC1: The proxy MUST start without errors when a valid model_aliases
        # list is present in config.yaml.
        config = AppConfig(
            backends={"default_backend": "openai"},
            model_aliases=[
                ModelAliasRule(
                    pattern="^gpt-4$", replacement="openrouter:openai/gpt-4"
                ),
                ModelAliasRule(
                    pattern="claude-(.*)", replacement="anthropic:claude-\\1"
                ),
            ],
        )

        # Should not raise any exceptions
        assert len(config.model_aliases) == 2
        assert config.model_aliases[0].pattern == "^gpt-4$"
        assert config.model_aliases[0].replacement == "openrouter:openai/gpt-4"

    def test_config_validation_empty_rules(self):
        """Test that configuration works when model_aliases is absent or empty."""
        # AC3: The proxy MUST start and operate normally if the model_aliases
        # key is absent from the configuration.
        config = AppConfig(
            backends={"default_backend": "openai"}
            # model_aliases not specified - should default to empty list
        )

        assert config.model_aliases == []

    def test_complex_regex_patterns(self, backend_service_with_aliases):
        """Test complex regex patterns with multiple capture groups."""
        config = AppConfig(
            backends={"default_backend": "openai"},
            model_aliases=[
                ModelAliasRule(
                    pattern="^(gpt|claude)-(\\d+)-(\\w+)$",
                    replacement="unified:\\1-\\2-\\3-model",
                )
            ],
        )

        backend_service = BackendService(
            factory=Mock(spec=BackendFactory),
            rate_limiter=Mock(spec=IRateLimiter),
            config=config,
            session_service=Mock(spec=ISessionService),
            app_state=Mock(spec=IApplicationState),
        )

        # Test GPT model
        result = backend_service._apply_model_aliases("gpt-4-turbo")
        assert result == "unified:gpt-4-turbo-model"

        # Test Claude model
        result = backend_service._apply_model_aliases("claude-3-sonnet")
        assert result == "unified:claude-3-sonnet-model"

        # Test non-matching model
        result = backend_service._apply_model_aliases("llama-2-70b")
        assert result == "llama-2-70b"


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
        from src.core.config.app_config import AppConfig, ModelAliasRule

        # Create config with file-based aliases
        config = AppConfig(
            backends={"default_backend": "openai"},
            model_aliases=[
                ModelAliasRule(pattern="^file-pattern$", replacement="file-replacement")
            ],
        )

        # Parse CLI arguments that will override the config file
        args = parse_cli_args(["--model-alias", "^cli-pattern$=cli-replacement"])

        # Mock the load_config function to return our test config
        import src.core.cli

        original_load_config = src.core.cli.load_config
        src.core.cli.load_config = lambda path=None, resolution=None: config

        try:
            # apply_cli_args returns a single AppConfig object by default
            result_config = apply_cli_args(args)

            # CLI should override config file
            assert len(result_config.model_aliases) == 1
            assert result_config.model_aliases[0].pattern == "^cli-pattern$"
            assert result_config.model_aliases[0].replacement == "cli-replacement"
        finally:
            # Restore original function
            src.core.cli.load_config = original_load_config

    def test_precedence_order_cli_env_config(self):
        """Test the complete precedence order: CLI > ENV > Config File."""
        import json
        import os
        import tempfile
        from pathlib import Path

        import yaml
        from src.core.cli import apply_cli_args, parse_cli_args
        from src.core.config.app_config import load_config

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
            final_config = apply_cli_args(cli_args)

            # Assert that CLI arguments have the highest precedence
            assert len(final_config.model_aliases) == 1
            assert final_config.model_aliases[0].pattern == "^cli-pattern$"
            assert final_config.model_aliases[0].replacement == "cli-replacement"

        finally:
            # Clean up
            Path(config_path).unlink()
            if "MODEL_ALIASES" in os.environ:
                del os.environ["MODEL_ALIASES"]
