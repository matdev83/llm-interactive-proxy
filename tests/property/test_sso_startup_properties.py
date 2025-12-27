"""
Property-based tests for SSO startup validation.

Feature: sso-authentication
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from src.core.auth.sso.config import AuthorizationConfig, ProviderConfig, SSOConfig
from src.core.auth.sso.exceptions import ConfigurationError
from src.core.auth.sso.startup_validation import (
    validate_startup_configuration,
)


# Generators for test data
@st.composite
def provider_config_strategy(draw):
    """Generate a valid ProviderConfig.

    OAuth2 providers require either discovery_url or authorize_url to be set.
    SAML providers require metadata_url to be set.
    """
    provider_type = draw(st.sampled_from(["oauth2", "saml"]))

    if provider_type == "oauth2":
        # OAuth2 requires either discovery_url or authorize_url
        use_discovery = draw(st.booleans())
        if use_discovery:
            discovery_url = draw(st.text(min_size=10, max_size=100))
            authorize_url = None
        else:
            discovery_url = None
            authorize_url = draw(st.text(min_size=10, max_size=100))
        metadata_url = None
    else:
        # SAML requires metadata_url
        discovery_url = None
        authorize_url = None
        metadata_url = draw(st.text(min_size=10, max_size=100))

    return ProviderConfig(
        type=provider_type,
        client_id=draw(st.text(min_size=1, max_size=50)),
        client_secret=draw(st.text(min_size=1, max_size=50)),
        discovery_url=discovery_url,
        authorize_url=authorize_url,
        metadata_url=metadata_url,
        scopes=draw(st.lists(st.text(min_size=1, max_size=20), max_size=5)),
    )


@st.composite
def sso_config_strategy(draw, enabled=True):
    """Generate a valid SSOConfig."""
    num_providers = draw(st.integers(min_value=1, max_value=3))
    providers = {}
    for i in range(num_providers):
        provider_name = f"provider_{i}"
        providers[provider_name] = draw(provider_config_strategy())

    return SSOConfig(
        enabled=enabled,
        session_lifetime_hours=draw(st.integers(min_value=1, max_value=168)),
        providers=providers,
        authorization=AuthorizationConfig(
            mode=draw(st.sampled_from(["single_user", "enterprise"]))
        ),
    )


@st.composite
def loopback_address_strategy(draw):
    """Generate a loopback address."""
    return draw(st.sampled_from(["127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1"]))


@st.composite
def non_loopback_address_strategy(draw):
    """Generate a non-loopback address."""
    return draw(
        st.sampled_from(
            [
                "0.0.0.0",
                "192.168.1.1",
                "10.0.0.1",
                "172.16.0.1",
                "8.8.8.8",
                "::",
                "2001:db8::1",
            ]
        )
    )


# Property 1: SSO Mode Activation
@settings(max_examples=30)  # Reduced from 50 for performance
@given(
    sso_config=sso_config_strategy(enabled=True),
    host=st.text(min_size=1, max_size=50),
)
def test_property_sso_mode_activation(sso_config, host):
    """
    Feature: sso-authentication, Property 1: SSO Mode Activation

    For any valid SSO configuration provided via CLI flag, environment variable,
    or config file, the proxy SHALL enter SSO authentication mode and require
    authentication for all requests.

    Validates: Requirements 1.1
    """
    # When SSO is enabled with valid configuration
    mode = validate_startup_configuration(
        host=host,
        sso_config=sso_config,
        legacy_api_keys=[],
        disable_auth=False,
    )

    # Then the mode should be SSO
    assert mode.mode == "sso"
    assert mode.sso_config is not None
    assert mode.sso_config.enabled is True
    assert len(mode.sso_config.providers) > 0


# Property 2: Legacy Auth Disabled in SSO Mode
@settings(max_examples=15)
@given(
    sso_config=sso_config_strategy(enabled=True),
    host=st.text(min_size=1, max_size=50),
    legacy_keys=st.lists(st.text(min_size=10, max_size=50), min_size=1, max_size=5),
)
def test_property_legacy_auth_disabled_in_sso_mode(sso_config, host, legacy_keys):
    """
    Feature: sso-authentication, Property 2: Legacy Auth Disabled in SSO Mode

    For any request containing a legacy static Bearer key, when SSO mode is enabled,
    the proxy SHALL reject the request and return a sandbox response (legacy keys
    are not valid in SSO mode).

    Validates: Requirements 1.2
    """
    # When SSO is enabled and legacy API keys are present
    # Then startup validation should raise ConfigurationError
    with pytest.raises(ConfigurationError) as exc_info:
        validate_startup_configuration(
            host=host,
            sso_config=sso_config,
            legacy_api_keys=legacy_keys,
            disable_auth=False,
        )

    # The error message should indicate legacy keys are not allowed
    assert (
        "legacy" in str(exc_info.value).lower() or "api" in str(exc_info.value).lower()
    )


# Property 3: Non-Loopback Startup Rejection
@settings(max_examples=50)
@given(host=non_loopback_address_strategy())
def test_property_non_loopback_startup_rejection(host):
    """
    Feature: sso-authentication, Property 3: Non-Loopback Startup Rejection

    For any bind address that is not 127.0.0.1 or ::1, when no authentication
    mode is configured, the proxy SHALL reject startup with an error.

    Validates: Requirements 1.4
    """
    # When no authentication is configured and binding to non-loopback
    # Then startup validation should raise ConfigurationError
    with pytest.raises(ConfigurationError) as exc_info:
        validate_startup_configuration(
            host=host,
            sso_config=None,
            legacy_api_keys=[],
            disable_auth=False,
        )

    # The error message should indicate non-loopback binding requires auth
    error_msg = str(exc_info.value).lower()
    assert (
        "loopback" in error_msg
        or "authentication" in error_msg
        or "127.0.0.1" in error_msg
    )


# Additional test: Loopback addresses should be allowed without auth
@settings(max_examples=50)
@given(host=loopback_address_strategy())
def test_loopback_addresses_allowed_without_auth(host):
    """
    Test that loopback addresses are allowed without authentication.

    This validates the inverse of Property 3 - loopback addresses should
    be allowed to start without authentication.
    """
    # When no authentication is configured and binding to loopback
    mode = validate_startup_configuration(
        host=host,
        sso_config=None,
        legacy_api_keys=[],
        disable_auth=False,
    )

    # Then the mode should be no_auth and validation should pass
    assert mode.mode == "no_auth"


# Additional test: Legacy mode detection
@settings(max_examples=50)
@given(
    host=st.text(min_size=1, max_size=50),
    legacy_keys=st.lists(st.text(min_size=10, max_size=50), min_size=1, max_size=5),
)
def test_legacy_mode_detection(host, legacy_keys):
    """
    Test that legacy authentication mode is correctly detected.
    """
    # When legacy API keys are configured without SSO
    mode = validate_startup_configuration(
        host=host,
        sso_config=None,
        legacy_api_keys=legacy_keys,
        disable_auth=False,
    )

    # Then the mode should be legacy
    assert mode.mode == "legacy"
    assert mode.legacy_api_keys == legacy_keys


# Additional test: SSO config without providers should fail
@settings(max_examples=50)
@given(host=st.text(min_size=1, max_size=50))
def test_sso_without_providers_fails(host):
    """
    Test that SSO mode without configured providers fails validation.
    """
    # When SSO is enabled but no providers are configured
    sso_config = SSOConfig(
        enabled=True,
        providers={},  # Empty providers
        authorization=AuthorizationConfig(mode="single_user"),
    )

    # Then startup validation should raise ConfigurationError
    with pytest.raises(ConfigurationError) as exc_info:
        validate_startup_configuration(
            host=host,
            sso_config=sso_config,
            legacy_api_keys=[],
            disable_auth=False,
        )

    # The error message should indicate providers are required
    assert "provider" in str(exc_info.value).lower()
