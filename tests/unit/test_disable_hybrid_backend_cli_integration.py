"""Integration tests for disable_hybrid_backend CLI to config flow."""

import os
from unittest.mock import patch

from src.core.cli import apply_cli_args, build_cli_parser
from src.core.config.app_config import AppConfig


class TestDisableHybridBackendCLIIntegration:
    """Test suite for CLI to config integration of disable_hybrid_backend."""

    @patch("src.core.cli.load_config")
    def test_cli_flag_sets_config_via_apply_cli_args(self, mock_load_config) -> None:
        """Test that --disable-hybrid-backend CLI flag sets config.backends.disable_hybrid_backend."""
        # Setup
        base_config = AppConfig()
        mock_load_config.return_value = base_config

        parser = build_cli_parser()
        args = parser.parse_args(["--disable-hybrid-backend"])

        # Apply CLI args
        result_config = apply_cli_args(args)

        # Verify
        assert result_config.backends.disable_hybrid_backend is True

    @patch("src.core.cli.load_config")
    def test_cli_without_flag_keeps_default_false(self, mock_load_config) -> None:
        """Test that without --disable-hybrid-backend flag, config remains False."""
        # Setup
        base_config = AppConfig()
        mock_load_config.return_value = base_config

        parser = build_cli_parser()
        args = parser.parse_args([])

        # Apply CLI args
        result_config = apply_cli_args(args)

        # Verify
        assert result_config.backends.disable_hybrid_backend is False

    @patch("src.core.cli.load_config")
    def test_cli_flag_sets_environment_variable(self, mock_load_config) -> None:
        """Test that --disable-hybrid-backend CLI flag sets DISABLE_HYBRID_BACKEND env var."""
        # Setup
        base_config = AppConfig()
        mock_load_config.return_value = base_config

        parser = build_cli_parser()
        args = parser.parse_args(["--disable-hybrid-backend"])

        # Clear env var before test
        if "DISABLE_HYBRID_BACKEND" in os.environ:
            del os.environ["DISABLE_HYBRID_BACKEND"]

        # Apply CLI args
        apply_cli_args(args)

        # Verify environment variable is set
        assert os.environ.get("DISABLE_HYBRID_BACKEND") == "1"

        # Cleanup
        if "DISABLE_HYBRID_BACKEND" in os.environ:
            del os.environ["DISABLE_HYBRID_BACKEND"]

    @patch("src.core.cli.load_config")
    def test_cli_flag_with_other_backend_options(self, mock_load_config) -> None:
        """Test that --disable-hybrid-backend works alongside other backend options."""
        # Setup
        base_config = AppConfig()
        mock_load_config.return_value = base_config

        parser = build_cli_parser()
        args = parser.parse_args(
            [
                "--disable-hybrid-backend",
                "--default-backend",
                "openai",
                "--disable-gemini-oauth-fallback",
            ]
        )

        # Apply CLI args
        result_config = apply_cli_args(args)

        # Verify all backend settings are applied
        assert result_config.backends.disable_hybrid_backend is True
        assert result_config.backends.default_backend == "openai"
        assert result_config.backends.disable_gemini_oauth_fallback is True
