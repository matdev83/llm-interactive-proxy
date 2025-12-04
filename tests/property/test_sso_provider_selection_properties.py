"""
Property-based tests for SSO provider selection and visibility.

These tests verify the correctness properties related to provider
configuration, visibility, and startup validation.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from src.core.auth.sso.config import AuthorizationConfig, ProviderConfig, SSOConfig
from src.core.auth.sso.exceptions import ConfigurationError
from src.core.auth.sso.sso_service import SSOService
from src.core.auth.sso.startup_validation import validate_startup_configuration


# Generators for test data
@st.composite
def provider_config_strategy(
    draw, enabled=None, has_credentials=True, has_endpoints=True
):
    """Generate a ProviderConfig with configurable validity."""
    provider_type = draw(st.sampled_from(["oauth2"]))

    if enabled is None:
        enabled_value = draw(st.booleans())
    else:
        enabled_value = enabled

    if has_credentials:
        client_id = draw(st.text(min_size=1, max_size=50))
        client_secret = draw(st.text(min_size=1, max_size=50))
    else:
        client_id = ""
        client_secret = ""

    if has_endpoints:
        # Either discovery_url or authorize_url must be present
        use_discovery = draw(st.booleans())
        if use_discovery:
            discovery_url = "https://example.com/.well-known/openid-configuration"
            authorize_url = None
        else:
            discovery_url = None
            authorize_url = "https://example.com/oauth/authorize"
    else:
        discovery_url = None
        authorize_url = None

    return ProviderConfig(
        type=provider_type,
        client_id=client_id,
        client_secret=client_secret,
        enabled=enabled_value,
        discovery_url=discovery_url,
        authorize_url=authorize_url,
        scopes=["openid", "email", "profile"],
    )


class TestProviderVisibilityProperties:
    """Property-based tests for provider visibility logic."""

    @given(
        st.lists(
            st.tuples(
                st.text(
                    min_size=1,
                    max_size=20,
                    alphabet=st.characters(whitelist_categories=("Ll", "Lu")),
                ),
                provider_config_strategy(
                    enabled=True, has_credentials=True, has_endpoints=True
                ),
            ),
            min_size=1,
            max_size=5,
            unique_by=lambda x: x[0],
        )
    )
    def test_all_providers_displayed_when_configured(self, providers_list):
        """
        Feature: sso-authentication, Property 28: All Providers Displayed When Configured

        For any SSO login page request, when all providers have valid configurations
        and are not explicitly disabled, all providers SHALL be displayed on the login page.

        Validates: Requirements 12.1, 12.2
        """
        providers = dict(providers_list)
        config = SSOConfig(
            enabled=True,
            providers=providers,
            authorization=AuthorizationConfig(mode="single_user"),
        )

        service = SSOService(config)
        enabled = service.get_enabled_providers()

        # All providers should be enabled
        assert len(enabled) == len(providers)
        for provider_name in providers:
            assert provider_name in enabled

    @given(
        st.lists(
            st.tuples(
                st.text(
                    min_size=1,
                    max_size=20,
                    alphabet=st.characters(whitelist_categories=("Ll", "Lu")),
                ),
                provider_config_strategy(
                    enabled=None, has_credentials=False, has_endpoints=True
                ),
            ),
            min_size=1,
            max_size=5,
            unique_by=lambda x: x[0],
        )
    )
    def test_provider_visibility_based_on_configuration(self, providers_list):
        """
        Feature: sso-authentication, Property 29: Provider Visibility Based on Configuration

        For any identity provider without valid configuration (missing client_id,
        client_secret, or discovery_url), that provider SHALL NOT appear on the SSO login page.

        Validates: Requirements 12.4
        """
        providers = dict(providers_list)
        config = SSOConfig(
            enabled=True,
            providers=providers,
            authorization=AuthorizationConfig(mode="single_user"),
        )

        service = SSOService(config)
        enabled = service.get_enabled_providers()

        # No providers should be enabled (all missing credentials)
        assert len(enabled) == 0

    @given(
        st.lists(
            st.tuples(
                st.text(
                    min_size=1,
                    max_size=20,
                    alphabet=st.characters(whitelist_categories=("Ll", "Lu")),
                ),
                provider_config_strategy(
                    enabled=False, has_credentials=True, has_endpoints=True
                ),
            ),
            min_size=1,
            max_size=5,
            unique_by=lambda x: x[0],
        )
    )
    def test_explicit_disable_enforcement(self, providers_list):
        """
        Feature: sso-authentication, Property 30: Explicit Disable Enforcement

        For any identity provider with "enabled: false" in configuration, that provider
        SHALL NOT appear on the SSO login page regardless of whether credentials are configured.

        Validates: Requirements 12.5, 13.1
        """
        providers = dict(providers_list)
        config = SSOConfig(
            enabled=True,
            providers=providers,
            authorization=AuthorizationConfig(mode="single_user"),
        )

        service = SSOService(config)
        enabled = service.get_enabled_providers()

        # No providers should be enabled (all explicitly disabled)
        assert len(enabled) == 0

        # Verify each provider is correctly identified as disabled
        for provider_name in providers:
            assert not service.is_provider_enabled(provider_name)


class TestStartupValidationProperties:
    """Property-based tests for startup validation."""

    @given(
        st.lists(
            st.tuples(
                st.text(
                    min_size=1,
                    max_size=20,
                    alphabet=st.characters(whitelist_categories=("Ll", "Lu")),
                ),
                st.one_of(
                    provider_config_strategy(
                        enabled=False, has_credentials=True, has_endpoints=True
                    ),
                    provider_config_strategy(
                        enabled=True, has_credentials=False, has_endpoints=True
                    ),
                    provider_config_strategy(
                        enabled=True, has_credentials=True, has_endpoints=False
                    ),
                ),
            ),
            min_size=1,
            max_size=5,
            unique_by=lambda x: x[0],
        )
    )
    def test_at_least_one_provider_required(self, providers_list):
        """
        Feature: sso-authentication, Property 32: At Least One Provider Required

        For any SSO configuration where all providers are disabled or unconfigured,
        the proxy SHALL reject startup with an error message.

        Validates: Requirements 13.4
        """
        providers = dict(providers_list)
        config = SSOConfig(
            enabled=True,
            providers=providers,
            authorization=AuthorizationConfig(mode="single_user"),
        )

        # All providers are either disabled or missing credentials/endpoints
        # Startup validation should fail
        with pytest.raises(ConfigurationError) as exc_info:
            validate_startup_configuration(
                host="127.0.0.1",
                sso_config=config,
            )

        assert "no identity providers are enabled" in str(exc_info.value).lower()

    @given(
        st.integers(min_value=1, max_value=5),
        st.integers(min_value=0, max_value=4),
    )
    def test_at_least_one_enabled_provider_allows_startup(
        self, total_providers, disabled_count
    ):
        """
        Test that startup succeeds when at least one provider is properly configured.

        This is the complement of Property 32 - ensuring that valid configurations pass.
        """
        # Ensure we have at least one enabled provider
        if disabled_count >= total_providers:
            disabled_count = total_providers - 1

        providers = {}

        # Add disabled providers
        for i in range(disabled_count):
            providers[f"disabled_{i}"] = ProviderConfig(
                type="oauth2",
                client_id=f"client_{i}",
                client_secret=f"secret_{i}",
                enabled=False,
                discovery_url="https://example.com/.well-known/openid-configuration",
            )

        # Add enabled providers
        for i in range(total_providers - disabled_count):
            providers[f"enabled_{i}"] = ProviderConfig(
                type="oauth2",
                client_id=f"client_{i}",
                client_secret=f"secret_{i}",
                enabled=True,
                discovery_url="https://example.com/.well-known/openid-configuration",
            )

        config = SSOConfig(
            enabled=True,
            providers=providers,
            authorization=AuthorizationConfig(mode="single_user"),
        )

        # Startup validation should succeed
        mode = validate_startup_configuration(
            host="127.0.0.1",
            sso_config=config,
        )

        assert mode.mode == "sso"
