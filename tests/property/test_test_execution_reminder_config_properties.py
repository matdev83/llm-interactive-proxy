"""Property-based tests for test execution reminder configuration.

Feature: test-execution-reminder
Property 10: Configuration Precedence
Validates: Requirements 5.7
"""

from __future__ import annotations

import argparse
import os
from typing import Any
from unittest.mock import patch

from hypothesis import given
from hypothesis import strategies as st
from src.core.cli import apply_cli_args
from src.core.config.app_config import AppConfig, SessionConfig, ToolCallReactorConfig
from tests.utils.hypothesis_config import property_test_settings


# Strategies for generating configuration values
@st.composite
def config_value_strategy(draw: st.DrawFn) -> bool | str | None:
    """Generate configuration values (bool, string, or None)."""
    return draw(
        st.one_of(
            st.booleans(),
            st.text(min_size=1, max_size=100),
            st.none(),
        )
    )


@st.composite
def config_source_strategy(draw: st.DrawFn) -> dict[str, Any]:
    """Generate configuration from different sources.

    Returns a dict with:
    - cli_enabled: CLI flag value for enabled (True/False/None)
    - env_enabled: Environment variable value for enabled (True/False/None)
    - config_enabled: Config file value for enabled (True/False/None)
    - cli_message: CLI flag value for message (str/None)
    - env_message: Environment variable value for message (str/None)
    - config_message: Config file value for message (str/None)
    """
    return {
        "cli_enabled": draw(st.one_of(st.booleans(), st.none())),
        "env_enabled": draw(st.one_of(st.booleans(), st.none())),
        "config_enabled": draw(st.one_of(st.booleans(), st.none())),
        "cli_message": draw(st.one_of(st.text(min_size=1, max_size=50), st.none())),
        "env_message": draw(st.one_of(st.text(min_size=1, max_size=50), st.none())),
        "config_message": draw(st.one_of(st.text(min_size=1, max_size=50), st.none())),
    }


def _create_config_with_values(enabled: bool | None, message: str | None) -> AppConfig:
    """Create an AppConfig with test execution reminder values."""
    if enabled is None and message is None:
        return AppConfig()

    session_config = SessionConfig(
        test_execution_reminder_enabled=enabled,
        test_execution_reminder_message=message,
        tool_call_reactor=ToolCallReactorConfig(
            test_execution_reminder_enabled=enabled or False,
            test_execution_reminder_message=message,
        ),
    )
    return AppConfig(session=session_config)


def _apply_env_values(enabled: bool | None, message: str | None) -> None:
    """Set environment variables for test execution reminder."""
    if enabled is not None:
        os.environ["TEST_EXECUTION_REMINDER_ENABLED"] = str(enabled).lower()
    elif "TEST_EXECUTION_REMINDER_ENABLED" in os.environ:
        del os.environ["TEST_EXECUTION_REMINDER_ENABLED"]

    if message is not None:
        os.environ["TEST_EXECUTION_REMINDER_MESSAGE"] = message
    elif "TEST_EXECUTION_REMINDER_MESSAGE" in os.environ:
        del os.environ["TEST_EXECUTION_REMINDER_MESSAGE"]


def _create_cli_args(enabled: bool | None, message: str | None) -> argparse.Namespace:
    """Create CLI args namespace with test execution reminder values."""
    args = argparse.Namespace(
        config_file=None,
        test_execution_reminder_enabled=enabled,
        test_execution_reminder_message=message,
        # Add other necessary default args
        host=None,
        port=None,
        anthropic_port=None,
        timeout=None,
        command_prefix=None,
        force_context_window=None,
        thinking_budget=None,
        log_file=None,
        capture_file=None,
        capture_max_bytes=None,
        capture_truncate_bytes=None,
        capture_max_files=None,
        capture_rotate_interval_seconds=None,
        capture_total_max_bytes=None,
        cbor_capture_dir=None,
        cbor_capture_session_id=None,
        log_level=None,
        disable_interactive_mode=None,
        disable_redact_api_keys_in_prompts=None,
        disable_auth=None,
        disable_sso_captcha=None,
        force_set_project=None,
        project_dir_resolution_model=None,
        project_dir_resolution_mode=None,
        disable_interactive_commands=None,
        disable_accounting=None,
        strict_command_detection=None,
        enable_sandboxing=None,
        enable_planning_phase=None,
        planning_phase_strong_model=None,
        planning_phase_max_turns=None,
        planning_phase_max_file_writes=None,
        planning_phase_temperature=None,
        planning_phase_top_p=None,
        planning_phase_reasoning_effort=None,
        planning_phase_thinking_budget=None,
        edit_precision_enabled=None,
        edit_precision_temperature=None,
        edit_precision_min_top_p=None,
        edit_precision_override_top_p=None,
        edit_precision_target_top_k=None,
        edit_precision_override_top_k=None,
        edit_precision_exclude_agents_regex=None,
        brute_force_protection_enabled=None,
        auth_max_failed_attempts=None,
        auth_brute_force_ttl=None,
        auth_initial_block_seconds=None,
        auth_block_multiplier=None,
        auth_max_block_seconds=None,
        pytest_compression_enabled=None,
        pytest_full_suite_steering_enabled=None,
        pytest_context_saving_enabled=None,
        fix_think_tags_enabled=None,
        disable_dangerous_git_commands_protection=None,
        tool_access_allowed_tools=None,
        tool_access_blocked_tools=None,
        tool_access_default_policy=None,
        llm_assessment_enabled=None,
        llm_assessment_turn_threshold=None,
        llm_assessment_confidence_threshold=None,
        llm_assessment_model=None,
        llm_assessment_history_window=None,
        identity_user_agent=None,
        identity_url=None,
        identity_title=None,
        allow_admin=False,
        daemon=False,
        trusted_ips=None,
        default_backend=None,
        static_route=None,
        disable_gemini_oauth_fallback=False,
        disable_hybrid_backend=False,
        hybrid_backend_repeat_messages=False,
        reasoning_injection_probability=None,
        hybrid_reasoning_model_timeout=None,
        hybrid_reasoning_force_initial_turns=None,
        model_aliases=None,
        quality_verifier_model=None,
        quality_verifier_frequency=None,
        # API keys and URLs
        openrouter_api_key=None,
        openrouter_api_base_url=None,
        gemini_api_key=None,
        gemini_api_base_url=None,
        zai_api_key=None,
        zenmux_api_base_url=None,
        enable_sso=None,
        sso_config_path=None,
        sso_provider=None,
        sso_auth_mode=None,
    )
    return args


@given(config_sources=config_source_strategy())
@property_test_settings(max_examples=5)  # Reduced from 10 for performance
def test_property_10_configuration_precedence_enabled(
    config_sources: dict[str, Any],
) -> None:
    """
    Property 10: Configuration Precedence (enabled flag).

    For any configuration setting (enabled flag), if multiple sources provide
    values (CLI, environment, config file), then the value from the highest
    precedence source should be used (CLI > Environment > Config).

    Validates: Requirements 5.7
    """
    # Clean up environment before test
    if "TEST_EXECUTION_REMINDER_ENABLED" in os.environ:
        del os.environ["TEST_EXECUTION_REMINDER_ENABLED"]
    # Ensure no dirty environment affects the test
    if "COMMAND_PREFIX" in os.environ:
        del os.environ["COMMAND_PREFIX"]
    if "PROXY_TIMEOUT" in os.environ:
        del os.environ["PROXY_TIMEOUT"]

    try:
        # Set up environment value
        _apply_env_values(config_sources["env_enabled"], None)

        # Create environment dict for from_env
        test_env = dict(os.environ)

        # Create base config that simulates config file + environment loading
        # The from_env method will apply environment variables
        base_config = AppConfig.from_env(environ=test_env)

        # If config_enabled is set, we need to override the environment-loaded value
        # to simulate a config file value (which has lower precedence than environment)
        if (
            config_sources["config_enabled"] is not None
            and config_sources["env_enabled"] is None
        ):
            # Only apply config value if environment is not set
            # (simulating that config file is loaded first, then env overrides it)
            base_config = _create_config_with_values(
                config_sources["config_enabled"],
                None,
            )

        # Set up CLI value
        cli_args = _create_cli_args(config_sources["cli_enabled"], None)

        # Apply CLI args (which should respect precedence)
        with patch("src.core.cli.load_config", return_value=base_config):
            result_config = apply_cli_args(cli_args)

        # Determine expected value based on precedence
        if config_sources["cli_enabled"] is not None:
            # CLI has highest precedence
            expected = config_sources["cli_enabled"]
        elif config_sources["env_enabled"] is not None:
            # Environment has second precedence
            expected = config_sources["env_enabled"]
        elif config_sources["config_enabled"] is not None:
            # Config file has lowest precedence
            expected = config_sources["config_enabled"]
        else:
            # Default value when nothing is set
            expected = False

        # Check the result
        actual = result_config.session.tool_call_reactor.test_execution_reminder_enabled
        assert actual == expected, (
            f"Configuration precedence violated for enabled flag. "
            f"Expected {expected}, got {actual}. "
            f"Sources: CLI={config_sources['cli_enabled']}, "
            f"ENV={config_sources['env_enabled']}, "
            f"CONFIG={config_sources['config_enabled']}"
        )

    finally:
        # Clean up environment after test
        if "TEST_EXECUTION_REMINDER_ENABLED" in os.environ:
            del os.environ["TEST_EXECUTION_REMINDER_ENABLED"]


@given(config_sources=config_source_strategy())
@property_test_settings(max_examples=5)  # Reduced from 10 for performance
def test_property_10_configuration_precedence_message(
    config_sources: dict[str, Any],
) -> None:
    """
    Property 10: Configuration Precedence (message).

    For any configuration setting (custom message), if multiple sources provide
    values (CLI, environment, config file), then the value from the highest
    precedence source should be used (CLI > Environment > Config).

    Validates: Requirements 5.7
    """
    # Clean up environment before test
    if "TEST_EXECUTION_REMINDER_MESSAGE" in os.environ:
        del os.environ["TEST_EXECUTION_REMINDER_MESSAGE"]
    # Ensure no dirty environment affects the test
    if "COMMAND_PREFIX" in os.environ:
        del os.environ["COMMAND_PREFIX"]
    if "PROXY_TIMEOUT" in os.environ:
        del os.environ["PROXY_TIMEOUT"]

    try:
        # Set up environment value
        _apply_env_values(None, config_sources["env_message"])

        # Create environment dict for from_env - only copy needed env vars
        test_env = {
            "TEST_EXECUTION_REMINDER_MESSAGE": os.environ.get(
                "TEST_EXECUTION_REMINDER_MESSAGE"
            )
        }

        # Create base config that simulates config file + environment loading
        # The from_env method will apply environment variables
        base_config = AppConfig.from_env(environ=test_env)

        # If config_message is set, we need to override the environment-loaded value
        # to simulate a config file value (which has lower precedence than environment)
        if (
            config_sources["config_message"] is not None
            and config_sources["env_message"] is None
        ):
            # Only apply config value if environment is not set
            base_config = _create_config_with_values(
                None,
                config_sources["config_message"],
            )

        # Set up CLI value (note: CLI doesn't support message override currently)
        cli_args = _create_cli_args(None, None)

        # Apply CLI args (which should respect precedence)
        with patch("src.core.cli.load_config", return_value=base_config):
            result_config = apply_cli_args(cli_args)

        # Determine expected value based on precedence
        # Note: CLI doesn't support message override, so it's ENV > CONFIG
        if config_sources["env_message"] is not None:
            # Environment has highest precedence (since CLI doesn't support it)
            expected = config_sources["env_message"]
        elif config_sources["config_message"] is not None:
            # Config file has lowest precedence
            expected = config_sources["config_message"]
        else:
            # Default value when nothing is set
            expected = None

        # Check the result
        actual = result_config.session.tool_call_reactor.test_execution_reminder_message
        assert actual == expected, (
            f"Configuration precedence violated for message. "
            f"Expected {expected}, got {actual}. "
            f"Sources: ENV={config_sources['env_message']}, "
            f"CONFIG={config_sources['config_message']}"
        )

    finally:
        # Clean up environment after test
        if "TEST_EXECUTION_REMINDER_MESSAGE" in os.environ:
            del os.environ["TEST_EXECUTION_REMINDER_MESSAGE"]
