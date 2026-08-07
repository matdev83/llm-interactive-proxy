"""Tests for think tags fix CLI integration."""

from src.core.cli import apply_cli_args, parse_cli_args
from src.core.config.app_config import AppConfig


class TestThinkTagsCliIntegration:
    """Test CLI integration for think tags fix feature."""

    def test_cli_flag_parsing(self):
        """Test that --fix-think-tags flag is parsed correctly."""
        args = parse_cli_args(["--fix-think-tags"])
        assert args.fix_think_tags_enabled is True

    def test_cli_flag_not_provided(self):
        """Test that flag defaults to None when not provided."""
        args = parse_cli_args([])
        assert getattr(args, "fix_think_tags_enabled", None) is None

    def test_cli_flag_applied_to_config(self):
        """Test that CLI flag is applied to configuration."""
        from unittest.mock import patch

        args = parse_cli_args(["--fix-think-tags"])
        with patch("src.core.cli.load_config", return_value=AppConfig()):
            config = apply_cli_args(args)

        if isinstance(config, tuple):
            config = config[0]

        assert config.session.fix_think_tags_enabled is True

    def test_environment_variable_integration(self):
        """Test that environment variable works correctly."""
        # Test enabled
        config = AppConfig.from_env(environ={"FIX_THINK_TAGS_ENABLED": "true"})
        assert config.session.fix_think_tags_enabled is True

        # Test disabled
        config = AppConfig.from_env(environ={"FIX_THINK_TAGS_ENABLED": "false"})
        assert config.session.fix_think_tags_enabled is False

        # Test default (not set)
        config = AppConfig.from_env(environ={})
        assert config.session.fix_think_tags_enabled is False

    def test_cli_overrides_environment(self):
        """Test that CLI flag overrides environment variable."""
        from unittest.mock import patch

        # Environment says false, CLI says true
        args = parse_cli_args(["--fix-think-tags"])

        # Create base config from environment
        base_config = AppConfig.from_env(environ={"FIX_THINK_TAGS_ENABLED": "false"})
        assert base_config.session.fix_think_tags_enabled is False

        # Apply CLI args which should override
        with patch("src.core.cli.load_config", return_value=AppConfig()):
            config = apply_cli_args(args)

        if isinstance(config, tuple):
            config = config[0]
        assert config.session.fix_think_tags_enabled is True

    def test_help_text_includes_flag(self):
        """Test that help text includes the new flag."""
        from src.core.cli import build_cli_parser

        parser = build_cli_parser()
        help_text = parser.format_help()

        assert "--fix-think-tags" in help_text
        assert "correction of improperly formatted <think> tags" in help_text

    def test_config_file_integration(self):
        """Test that config file integration works."""
        config_data = {"session": {"fix_think_tags_enabled": True}}
        config = AppConfig(**config_data)
        assert config.session.fix_think_tags_enabled is True

    def test_default_configuration(self):
        """Test that default configuration has feature disabled."""
        config = AppConfig()
        assert config.session.fix_think_tags_enabled is False
