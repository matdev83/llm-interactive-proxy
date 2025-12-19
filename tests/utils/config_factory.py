"""Factory functions for creating test configurations."""

from typing import Any

from src.core.config.app_config import (
    AppConfig,
    AuthConfig,
    BackendSettings,
    LoggingConfig,
    SessionConfig,
)


def create_test_config(**overrides: Any) -> AppConfig:
    """
    Create an AppConfig instance for testing with optional overrides.

    This factory handles the immutable nature of Pydantic models by constructing
    nested config objects properly.

    Args:
        **overrides: Keyword arguments to override default config values.
                    Supports nested overrides via nested dicts.

    Returns:
        AppConfig: A fully configured AppConfig instance.

    Examples:
        >>> config = create_test_config(host="0.0.0.0", port=9000)
        >>> config = create_test_config(auth={"disable_auth": True})
        >>> config = create_test_config(
        ...     backends={"default_backend": "mock"},
        ...     auth={"disable_auth": True, "api_keys": []}
        ... )
    """
    # Handle auth config
    auth_overrides = overrides.pop("auth", None)
    if auth_overrides:
        if isinstance(auth_overrides, dict):
            auth_config = AuthConfig(**auth_overrides)
        else:
            auth_config = auth_overrides
    else:
        # Default auth config for tests - disabled authentication
        auth_config = AuthConfig(
            disable_auth=True, api_keys=[], redact_api_keys_in_prompts=False
        )

    # Handle backends config
    backends_overrides = overrides.pop("backends", None)
    if backends_overrides:
        if isinstance(backends_overrides, dict):
            backends_config = BackendSettings(**backends_overrides)
        else:
            backends_config = backends_overrides
    else:
        backends_config = BackendSettings(default_backend="mock")

    # Handle logging config
    logging_overrides = overrides.pop("logging", None)
    if logging_overrides:
        if isinstance(logging_overrides, dict):
            logging_config = LoggingConfig(**logging_overrides)
        else:
            logging_config = logging_overrides
        overrides["logging"] = logging_config

    # Handle session config
    session_overrides = overrides.pop("session", None)
    if session_overrides:
        if isinstance(session_overrides, dict):
            session_config = SessionConfig(**session_overrides)
        else:
            session_config = session_overrides
        overrides["session"] = session_config

    # Create config with all components
    return AppConfig(
        auth=auth_config,
        backends=backends_config,
        **overrides,
    )


def create_auth_enabled_config(**overrides: Any) -> AppConfig:
    """
    Create an AppConfig with authentication enabled for testing.

    Args:
        **overrides: Additional overrides for the config.

    Returns:
        AppConfig: A config with authentication enabled and test API keys.
    """
    auth_config = AuthConfig(
        disable_auth=False,
        api_keys=["test_api_key_123"],
        redact_api_keys_in_prompts=True,
    )

    return create_test_config(auth=auth_config, **overrides)
