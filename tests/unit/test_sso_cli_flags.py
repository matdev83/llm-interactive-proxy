"""
Unit tests for SSO CLI flags.

Tests the --sso-provider and --sso-auth-mode CLI flags.
"""

import pytest


def test_sso_provider_flag_parsing():
    """
    Test that --sso-provider flag is parsed correctly.

    Requirement 1.1: CLI flag to select specific SSO provider.
    """
    from src.core.cli import build_cli_parser

    parser = build_cli_parser()

    # Test with provider flag
    args = parser.parse_args(["--sso-provider", "google"])
    assert args.sso_provider == "google"

    # Test without flag
    args = parser.parse_args([])
    assert args.sso_provider is None


def test_sso_auth_mode_flag_parsing():
    """
    Test that --sso-auth-mode flag is parsed correctly.

    Requirement 1.1: CLI flag to configure SSO authorization mode.
    """
    from src.core.cli import build_cli_parser

    parser = build_cli_parser()

    # Test single_user mode
    args = parser.parse_args(["--sso-auth-mode", "single_user"])
    assert args.sso_auth_mode == "single_user"

    # Test enterprise mode
    args = parser.parse_args(["--sso-auth-mode", "enterprise"])
    assert args.sso_auth_mode == "enterprise"

    # Test without flag
    args = parser.parse_args([])
    assert args.sso_auth_mode is None


def test_sso_auth_mode_rejects_invalid_values():
    """
    Test that --sso-auth-mode rejects invalid values.
    """
    from src.core.cli import build_cli_parser

    parser = build_cli_parser()

    # Test invalid mode
    with pytest.raises(SystemExit):
        parser.parse_args(["--sso-auth-mode", "invalid_mode"])


def test_combined_sso_flags():
    """
    Test multiple SSO flags can be used together.

    Requirement 1.1: Enable and configure SSO via CLI.
    """
    from src.core.cli import build_cli_parser

    parser = build_cli_parser()

    args = parser.parse_args(
        [
            "--enable-sso",
            "--sso-provider",
            "github",
            "--sso-auth-mode",
            "enterprise",
            "--sso-config",
            "/path/to/config.yaml",
        ]
    )

    assert args.enable_sso is True
    assert args.sso_provider == "github"
    assert args.sso_auth_mode == "enterprise"
    assert args.sso_config_path == "/path/to/config.yaml"


def test_sso_provider_flag_in_help():
    """
    Test that SSO provider flag appears in help text.
    """
    from src.core.cli import build_cli_parser

    parser = build_cli_parser()
    help_text = parser.format_help()

    assert "--sso-provider" in help_text
    assert "PROVIDER" in help_text


def test_sso_auth_mode_flag_in_help():
    """
    Test that SSO auth mode flag appears in help text.
    """
    from src.core.cli import build_cli_parser

    parser = build_cli_parser()
    help_text = parser.format_help()

    assert "--sso-auth-mode" in help_text
    assert "single_user" in help_text
    assert "enterprise" in help_text
