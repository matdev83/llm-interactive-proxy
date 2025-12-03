"""Property-based tests for SSO configuration models.

Feature: sso-authentication
Property: 27
Validates: Requirements 12.6
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st
from src.core.auth.sso.config import ProviderConfig, SSOConfig
from tests.utils.hypothesis_config import property_test_settings

# Strategy for generating valid provider types
provider_type_strategy = st.sampled_from(["oauth2", "saml"])


# Strategy for generating valid OAuth2/OIDC/SAML configuration
@st.composite
def provider_config_strategy(draw: st.DrawFn) -> ProviderConfig:
    """Generate valid ProviderConfig instances.

    According to Requirements 12.6, any supported IdP configuration SHALL accept
    standard OAuth2/OIDC/SAML parameters (client_id, client_secret, and either
    discovery_url or metadata_url) without requiring provider-specific fields.
    """
    provider_type = draw(provider_type_strategy)

    # Generate required fields
    client_id = draw(st.text(min_size=1, max_size=100))
    client_secret = draw(st.text(min_size=1, max_size=100))

    # Generate optional fields based on provider type
    if provider_type == "oauth2":
        # OAuth2/OIDC can use discovery_url OR manual URLs
        use_discovery = draw(st.booleans())
        if use_discovery:
            discovery_url = draw(st.text(min_size=1, max_size=200))
            return ProviderConfig(
                type=provider_type,
                client_id=client_id,
                client_secret=client_secret,
                discovery_url=discovery_url,
                scopes=draw(st.lists(st.text(min_size=1, max_size=50), max_size=5)),
            )
        else:
            # Manual OAuth2 configuration
            authorize_url = draw(st.text(min_size=1, max_size=200))
            token_url = draw(st.text(min_size=1, max_size=200))
            userinfo_url = draw(st.text(min_size=1, max_size=200))
            return ProviderConfig(
                type=provider_type,
                client_id=client_id,
                client_secret=client_secret,
                authorize_url=authorize_url,
                token_url=token_url,
                userinfo_url=userinfo_url,
                scopes=draw(st.lists(st.text(min_size=1, max_size=50), max_size=5)),
            )
    else:  # SAML
        metadata_url = draw(st.text(min_size=1, max_size=200))
        return ProviderConfig(
            type=provider_type,
            client_id=client_id,
            client_secret=client_secret,
            metadata_url=metadata_url,
        )


@given(provider_config=provider_config_strategy())
@property_test_settings()
def test_property_27_idp_configuration_schema(
    provider_config: ProviderConfig,
) -> None:
    """
    Property 27: IdP Configuration Schema.

    For any supported identity provider configuration, the proxy SHALL accept
    standard OAuth2/OIDC/SAML parameters (client_id, client_secret, and either
    discovery_url or metadata_url) without requiring provider-specific fields.

    Validates: Requirements 12.6

    Feature: sso-authentication, Property 27: IdP Configuration Schema
    """
    # Verify that the configuration has required fields
    assert provider_config.client_id is not None
    assert len(provider_config.client_id) > 0
    assert provider_config.client_secret is not None
    assert len(provider_config.client_secret) > 0

    # Verify that the provider type is valid
    assert provider_config.type in ["oauth2", "saml"]

    # Verify that appropriate discovery/metadata URL is present
    if provider_config.type == "oauth2":
        # OAuth2 must have either discovery_url OR manual URLs
        has_discovery = provider_config.discovery_url is not None
        has_manual = (
            provider_config.authorize_url is not None
            and provider_config.token_url is not None
            and provider_config.userinfo_url is not None
        )
        assert (
            has_discovery or has_manual
        ), "OAuth2 provider must have either discovery_url or manual URLs"
    elif provider_config.type == "saml":
        # SAML must have metadata_url
        assert provider_config.metadata_url is not None
        assert len(provider_config.metadata_url) > 0


@given(
    provider_name=st.text(min_size=1, max_size=50),
    provider_config=provider_config_strategy(),
)
@property_test_settings()
def test_property_27_sso_config_accepts_standard_params(
    provider_name: str,
    provider_config: ProviderConfig,
) -> None:
    """
    Property 27: SSO Config accepts standard parameters.

    For any provider configuration with standard OAuth2/OIDC/SAML parameters,
    the SSOConfig SHALL accept and store the configuration without errors.

    Validates: Requirements 12.6

    Feature: sso-authentication, Property 27: IdP Configuration Schema
    """
    # Create SSOConfig with the provider
    sso_config = SSOConfig(
        enabled=True,
        providers={provider_name: provider_config},
    )

    # Verify that the provider was stored correctly
    assert provider_name in sso_config.providers
    stored_config = sso_config.providers[provider_name]

    # Verify all standard parameters are preserved
    assert stored_config.client_id == provider_config.client_id
    assert stored_config.client_secret == provider_config.client_secret
    assert stored_config.type == provider_config.type

    # Verify type-specific parameters are preserved
    if provider_config.type == "oauth2":
        if provider_config.discovery_url is not None:
            assert stored_config.discovery_url == provider_config.discovery_url
        if provider_config.authorize_url is not None:
            assert stored_config.authorize_url == provider_config.authorize_url
            assert stored_config.token_url == provider_config.token_url
            assert stored_config.userinfo_url == provider_config.userinfo_url
    elif provider_config.type == "saml":
        assert stored_config.metadata_url == provider_config.metadata_url


@given(
    provider_configs=st.dictionaries(
        keys=st.text(min_size=1, max_size=50),
        values=provider_config_strategy(),
        min_size=1,
        max_size=5,
    )
)
@property_test_settings()
def test_property_27_multiple_providers_configuration(
    provider_configs: dict[str, ProviderConfig],
) -> None:
    """
    Property 27: Multiple providers configuration.

    For any set of provider configurations, the SSOConfig SHALL accept and
    store all providers without conflicts or data loss.

    Validates: Requirements 12.6

    Feature: sso-authentication, Property 27: IdP Configuration Schema
    """
    # Create SSOConfig with multiple providers
    sso_config = SSOConfig(
        enabled=True,
        providers=provider_configs,
    )

    # Verify all providers were stored
    assert len(sso_config.providers) == len(provider_configs)

    # Verify each provider configuration is preserved correctly
    for provider_name, expected_config in provider_configs.items():
        assert provider_name in sso_config.providers
        stored_config = sso_config.providers[provider_name]

        # Verify standard parameters
        assert stored_config.client_id == expected_config.client_id
        assert stored_config.client_secret == expected_config.client_secret
        assert stored_config.type == expected_config.type


@given(
    provider_type=provider_type_strategy,
    client_id=st.text(min_size=1, max_size=100),
    client_secret=st.text(min_size=1, max_size=100),
    discovery_url=st.text(min_size=1, max_size=200),
)
@property_test_settings()
def test_property_27_oauth2_with_discovery_url(
    provider_type: str,
    client_id: str,
    client_secret: str,
    discovery_url: str,
) -> None:
    """
    Property 27: OAuth2 with discovery URL.

    For any OAuth2 provider with client_id, client_secret, and discovery_url,
    the configuration SHALL be valid without requiring additional fields.

    Validates: Requirements 12.6

    Feature: sso-authentication, Property 27: IdP Configuration Schema
    """
    if provider_type != "oauth2":
        return  # Skip SAML providers

    # Create minimal OAuth2 configuration with discovery
    config = ProviderConfig(
        type="oauth2",
        client_id=client_id,
        client_secret=client_secret,
        discovery_url=discovery_url,
    )

    # Verify configuration is valid
    assert config.type == "oauth2"
    assert config.client_id == client_id
    assert config.client_secret == client_secret
    assert config.discovery_url == discovery_url

    # Verify it can be used in SSOConfig
    sso_config = SSOConfig(
        enabled=True,
        providers={"test-provider": config},
    )
    assert "test-provider" in sso_config.providers


@given(
    client_id=st.text(min_size=1, max_size=100),
    client_secret=st.text(min_size=1, max_size=100),
    metadata_url=st.text(min_size=1, max_size=200),
)
@property_test_settings()
def test_property_27_saml_with_metadata_url(
    client_id: str,
    client_secret: str,
    metadata_url: str,
) -> None:
    """
    Property 27: SAML with metadata URL.

    For any SAML provider with client_id, client_secret, and metadata_url,
    the configuration SHALL be valid without requiring additional fields.

    Validates: Requirements 12.6

    Feature: sso-authentication, Property 27: IdP Configuration Schema
    """
    # Create minimal SAML configuration
    config = ProviderConfig(
        type="saml",
        client_id=client_id,
        client_secret=client_secret,
        metadata_url=metadata_url,
    )

    # Verify configuration is valid
    assert config.type == "saml"
    assert config.client_id == client_id
    assert config.client_secret == client_secret
    assert config.metadata_url == metadata_url

    # Verify it can be used in SSOConfig
    sso_config = SSOConfig(
        enabled=True,
        providers={"test-saml-provider": config},
    )
    assert "test-saml-provider" in sso_config.providers
