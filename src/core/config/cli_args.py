"""
CLI argument parsing for the LLM Proxy.

This module provides CLI argument parsing functionality to support
command-line configuration of the proxy server, including SSO settings.
"""

import argparse
import os
from typing import Any


def parse_cli_args(args: list[str] | None = None) -> dict[str, Any]:
    """
    Parse command-line arguments.

    Args:
        args: List of arguments to parse (defaults to sys.argv)

    Returns:
        Dictionary of parsed arguments that can be used to override config
    """
    parser = argparse.ArgumentParser(
        description="LLM Interactive Proxy Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Server settings
    parser.add_argument(
        "--host",
        type=str,
        help="Host address to bind to (default: 127.0.0.1)",
    )

    parser.add_argument(
        "--port",
        type=int,
        help="Port to bind to (default: 8000)",
    )

    # SSO authentication settings
    parser.add_argument(
        "--sso-enabled",
        action="store_true",
        help="Enable SSO authentication mode",
    )

    parser.add_argument(
        "--sso-provider",
        type=str,
        help="SSO provider to use (e.g., google, microsoft, github)",
    )

    parser.add_argument(
        "--sso-auth-mode",
        type=str,
        choices=["single_user", "enterprise"],
        help="Authorization mode: single_user (confirmation code) or enterprise (API)",
    )

    parser.add_argument(
        "--sso-database-path",
        type=str,
        help="Path to SSO database file (default: ./var/sso_auth.db)",
    )

    parser.add_argument(
        "--sso-session-lifetime",
        type=int,
        help="SSO session lifetime in hours (default: 24)",
    )

    # Parse arguments
    parsed_args = parser.parse_args(args)

    # Convert to dictionary, filtering out None values
    result: dict[str, Any] = {}

    if parsed_args.host is not None:
        result["host"] = parsed_args.host

    if parsed_args.port is not None:
        result["port"] = parsed_args.port

    if parsed_args.sso_enabled:
        result["sso_enabled"] = True

    if parsed_args.sso_provider is not None:
        result["sso_provider"] = parsed_args.sso_provider

    if parsed_args.sso_auth_mode is not None:
        result["sso_auth_mode"] = parsed_args.sso_auth_mode

    if parsed_args.sso_database_path is not None:
        result["sso_database_path"] = parsed_args.sso_database_path

    if parsed_args.sso_session_lifetime is not None:
        result["sso_session_lifetime"] = parsed_args.sso_session_lifetime

    return result


def apply_cli_overrides(env_dict: dict[str, str], cli_args: dict[str, Any]) -> None:
    """
    Apply CLI argument overrides to environment dictionary.

    This modifies the environment dictionary in-place to include
    CLI argument values, which take precedence over environment variables.

    Args:
        env_dict: Environment dictionary to modify
        cli_args: Parsed CLI arguments
    """
    # Map CLI args to environment variable names
    if "host" in cli_args:
        env_dict["APP_HOST"] = cli_args["host"]

    if "port" in cli_args:
        env_dict["APP_PORT"] = str(cli_args["port"])

    if "sso_enabled" in cli_args:
        env_dict["SSO_ENABLED"] = "true"

    if "sso_provider" in cli_args:
        env_dict["SSO_PROVIDER"] = cli_args["sso_provider"]

    if "sso_auth_mode" in cli_args:
        env_dict["SSO_AUTH_MODE"] = cli_args["sso_auth_mode"]

    if "sso_database_path" in cli_args:
        env_dict["SSO_DATABASE_PATH"] = cli_args["sso_database_path"]

    if "sso_session_lifetime" in cli_args:
        env_dict["SSO_SESSION_LIFETIME_HOURS"] = str(cli_args["sso_session_lifetime"])


def get_config_with_cli_args() -> dict[str, str]:
    """
    Get configuration environment with CLI argument overrides.

    Returns:
        Environment dictionary with CLI overrides applied
    """
    # Start with current environment
    env_dict = dict(os.environ)

    # Parse CLI arguments
    cli_args = parse_cli_args()

    # Apply CLI overrides
    apply_cli_overrides(env_dict, cli_args)

    return env_dict
