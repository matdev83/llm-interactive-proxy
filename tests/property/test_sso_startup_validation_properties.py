"""Property-based tests for startup validation and mode switching.

Feature: sso-authentication
Properties: 1, 2, 3
Validates: Requirements 1.1, 1.2, 1.4
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st
from src.core.auth.sso.config import AuthorizationConfig, ProviderConfig, SSOConfig
from src.core.auth.sso.exceptions import ConfigurationError
from src.core.auth.sso.startup_validation import (
    validate_startup_configuration,
)
from tests.utils.hypothesis_config import property_test_settings


# Strategies
@st.composite
def sso_config_strategy(draw: st.DrawFn) -> SSOConfig:
    """Generate valid SSOConfig."""
    providers = {
        "google": ProviderConfig(
            type="oauth2",
            client_id="test-client-id",
            client_secret="test-secret",
            discovery_url="https://accounts.google.com/.well-known/openid-configuration",
        )
    }

    return SSOConfig(
        enabled=True,
        providers=providers,
        authorization=AuthorizationConfig(mode="single_user"),
    )


@st.composite
def loopback_address_strategy(draw: st.DrawFn) -> str:
    """Generate loopback addresses."""
    return draw(st.sampled_from(["127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1"]))


@st.composite
def non_loopback_address_strategy(draw: st.DrawFn) -> str:
    """Generate non-loopback addresses."""
    return draw(st.sampled_from(["0.0.0.0", "192.168.1.1", "10.0.0.1", "example.com"]))


@given(
    sso_config=sso_config_strategy(),
    host=loopback_address_strategy(),
)
@property_test_settings()
def test_property_1_sso_mode_activation(
    sso_config: SSOConfig,
    host: str,
) -> None:
    """
    Property 1: SSO Mode Activation.

    For any valid SSO configuration provided, the proxy SHALL enter SSO
    authentication mode.

    Validates: Requirements 1.1

    Feature: sso-authentication, Property 1: SSO Mode Activation
    """
    mode = validate_startup_configuration(
        host=host,
        sso_config=sso_config,
        legacy_api_keys=[],
    )

    assert mode.mode == "sso"
    assert mode.sso_config == sso_config


@given(
    sso_config=sso_config_strategy(),
    host=loopback_address_strategy(),
    api_keys=st.lists(st.text(min_size=1), min_size=1),
)
@property_test_settings()
def test_property_2_legacy_auth_disabled_in_sso_mode(
    sso_config: SSOConfig,
    host: str,
    api_keys: list[str],
) -> None:
    """
    Property 2: Legacy Auth Disabled in SSO Mode.

    For any configuration where SSO is enabled, legacy API keys SHALL NOT be
    allowed (to prevent confusion/security holes).

    Validates: Requirements 1.2

    Feature: sso-authentication, Property 2: Legacy Auth Disabled in SSO Mode
    """
    with pytest.raises(ConfigurationError) as exc_info:
        validate_startup_configuration(
            host=host,
            sso_config=sso_config,
            legacy_api_keys=api_keys,
        )

    assert "Legacy API keys are not allowed" in str(exc_info.value)


@given(
    host=non_loopback_address_strategy(),
)
@property_test_settings()
def test_property_3_non_loopback_startup_rejection(
    host: str,
) -> None:
    """
    Property 3: Non-Loopback Startup Rejection.

    For any bind address that is not 127.0.0.1 or ::1, when no authentication
    mode is configured, the proxy SHALL reject startup with an error.

    Validates: Requirements 1.4

    Feature: sso-authentication, Property 3: Non-Loopback Startup Rejection
    """
    # No SSO, no legacy keys
    with pytest.raises(ConfigurationError) as exc_info:
        validate_startup_configuration(
            host=host,
            sso_config=None,
            legacy_api_keys=[],
        )

    assert "Cannot start proxy on non-loopback address" in str(exc_info.value)


@given(
    host=loopback_address_strategy(),
)
@property_test_settings()
def test_no_auth_loopback_allowed(
    host: str,
) -> None:
    """Test that no-auth is allowed on loopback addresses."""
    mode = validate_startup_configuration(
        host=host,
        sso_config=None,
        legacy_api_keys=[],
    )

    assert mode.mode == "no_auth"
