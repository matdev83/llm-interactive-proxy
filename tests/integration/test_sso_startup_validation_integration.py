"""
Integration tests for SSO startup validation.

Tests the integration of startup validation with the application bootstrap.
"""

import pytest
from fastapi import FastAPI
from src.core.auth.sso.config import AuthorizationConfig, ProviderConfig, SSOConfig
from src.core.auth.sso.exceptions import ConfigurationError

# Feature: sso-authentication, Property: Startup validation integration
# Validates Requirements 1.2, 1.4, 13.4


def test_sso_enabled_rejects_legacy_api_keys():
    """
    Test that SSO mode rejects configuration with legacy API keys.

    Requirement 1.2: WHEN SSO mode is enabled THEN the Proxy SHALL disable
    the legacy static Bearer key authentication mechanism.
    """
    from src.core.auth.sso.startup_validation import validate_startup_configuration

    # Create SSO config with a valid provider
    sso_config = SSOConfig(
        enabled=True,
        providers={
            "google": ProviderConfig(
                type="oauth2",
                client_id="test-client-id",
                client_secret="test-secret",
                discovery_url="https://accounts.google.com/.well-known/openid-configuration",
                enabled=True,
            )
        },
        authorization=AuthorizationConfig(mode="single_user"),
        database_path=":memory:",
    )

    # Should raise error when legacy API keys are present
    with pytest.raises(ConfigurationError) as exc_info:
        validate_startup_configuration(
            host="127.0.0.1",
            sso_config=sso_config,
            legacy_api_keys=["some-api-key"],
            disable_auth=False,
        )

    assert "Legacy API keys are not allowed" in str(exc_info.value)


def test_sso_requires_at_least_one_enabled_provider():
    """
    Test that SSO mode requires at least one enabled provider.

    Requirement 13.4: WHEN all providers are disabled THEN the Proxy SHALL
    reject startup with an error message.
    """
    from src.core.auth.sso.startup_validation import validate_startup_configuration

    # Create SSO config with no enabled providers
    sso_config = SSOConfig(
        enabled=True,
        providers={
            "google": ProviderConfig(
                type="oauth2",
                client_id="test-client-id",
                client_secret="test-secret",
                discovery_url="https://accounts.google.com/.well-known/openid-configuration",
                enabled=False,  # Explicitly disabled
            )
        },
        authorization=AuthorizationConfig(mode="single_user"),
        database_path=":memory:",
    )

    # Should raise error when no providers are enabled
    with pytest.raises(ConfigurationError) as exc_info:
        validate_startup_configuration(
            host="127.0.0.1",
            sso_config=sso_config,
            legacy_api_keys=[],
            disable_auth=False,
        )

    assert "no identity providers are enabled" in str(exc_info.value)


def test_non_loopback_without_auth_rejected():
    """
    Test that non-loopback binding without auth is rejected.

    Requirement 1.4: WHEN no authentication mode is configured AND the proxy
    binds to a non-loopback address THEN the Proxy SHALL reject startup.
    """
    from src.core.auth.sso.startup_validation import validate_startup_configuration

    # Should raise error when binding to non-loopback without auth
    with pytest.raises(ConfigurationError) as exc_info:
        validate_startup_configuration(
            host="0.0.0.0",  # Non-loopback
            sso_config=None,
            legacy_api_keys=[],
            disable_auth=False,
        )

    assert "non-loopback address" in str(exc_info.value)
    assert "without authentication" in str(exc_info.value)


def test_loopback_without_auth_allowed():
    """
    Test that loopback binding without auth is allowed.

    Requirement 1.3: WHEN no authentication mode is configured AND the proxy
    binds to 127.0.0.1 THEN the Proxy SHALL allow unauthenticated access.
    """
    from src.core.auth.sso.startup_validation import validate_startup_configuration

    # Should succeed for loopback binding without auth
    mode = validate_startup_configuration(
        host="127.0.0.1",
        sso_config=None,
        legacy_api_keys=[],
        disable_auth=False,
    )

    assert mode.mode == "no_auth"


def test_sso_mode_validation_success():
    """
    Test successful SSO mode validation with proper configuration.
    """
    from src.core.auth.sso.startup_validation import validate_startup_configuration

    # Create valid SSO config
    sso_config = SSOConfig(
        enabled=True,
        providers={
            "google": ProviderConfig(
                type="oauth2",
                client_id="test-client-id",
                client_secret="test-secret",
                discovery_url="https://accounts.google.com/.well-known/openid-configuration",
                enabled=True,
            )
        },
        authorization=AuthorizationConfig(mode="single_user"),
        database_path=":memory:",
    )

    # Should succeed with valid SSO config
    mode = validate_startup_configuration(
        host="127.0.0.1",
        sso_config=sso_config,
        legacy_api_keys=[],
        disable_auth=False,
    )

    assert mode.mode == "sso"
    assert mode.sso_config is not None
    assert len(mode.sso_config.providers) == 1


def test_middleware_disables_legacy_auth_when_sso_enabled(tmp_path):
    """
    Test that middleware configuration disables legacy auth when SSO is enabled.

    Requirement 1.2: Legacy authentication should be disabled when SSO is active.
    """
    from src.core.app.middleware_config import configure_middleware

    # Create a mock config with SSO enabled and legacy API keys
    class MockAuthConfig:
        disable_auth = False
        api_keys = ["legacy-key-1", "legacy-key-2"]
        trusted_ips = []
        brute_force_protection = None
        auth_token = None

    class MockSSOConfig:
        enabled = True
        database_path = str(tmp_path / "test.db")
        captcha = None
        authorization = None
        providers = {}

    class MockLogging:
        request_logging = False
        response_logging = False

    class MockRewriting:
        enabled = False

    class MockConfig:
        auth = MockAuthConfig()
        sso = MockSSOConfig()
        logging = MockLogging()
        rewriting = MockRewriting()
        host = "127.0.0.1"
        port = 8000
        public_url = None

    app = FastAPI()
    config = MockConfig()

    # Configure middleware
    configure_middleware(app, config)

    # Check that APIKeyMiddleware was NOT added (legacy auth disabled)
    from src.core.security import APIKeyMiddleware

    api_key_middleware_found = False
    for middleware in app.user_middleware:
        if middleware.cls == APIKeyMiddleware:
            api_key_middleware_found = True
            break

    assert (
        not api_key_middleware_found
    ), "APIKeyMiddleware should not be added when SSO is enabled"


def test_middleware_allows_legacy_auth_when_sso_disabled():
    """
    Test that middleware configuration allows legacy auth when SSO is disabled.
    """
    from src.core.app.middleware_config import configure_middleware

    # Create a mock config with SSO disabled and legacy API keys
    class MockAuthConfig:
        disable_auth = False
        api_keys = ["legacy-key-1", "legacy-key-2"]
        trusted_ips = []
        brute_force_protection = None
        auth_token = None

    class MockLogging:
        request_logging = False
        response_logging = False

    class MockRewriting:
        enabled = False

    class MockConfig:
        auth = MockAuthConfig()
        sso = None
        logging = MockLogging()
        rewriting = MockRewriting()

    app = FastAPI()
    config = MockConfig()

    # Configure middleware
    configure_middleware(app, config)

    # Check that APIKeyMiddleware WAS added (legacy auth enabled)
    from src.core.security import APIKeyMiddleware

    api_key_middleware_found = False
    for middleware in app.user_middleware:
        if middleware.cls == APIKeyMiddleware:
            api_key_middleware_found = True
            break

    assert (
        api_key_middleware_found
    ), "APIKeyMiddleware should be added when SSO is disabled"
