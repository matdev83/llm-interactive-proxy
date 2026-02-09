"""Property tests for Multi User Mode non-localhost with authentication.

**Feature: proxy-access-modes, Property 3: Multi User Mode allows non-localhost with authentication**

**Validates: Requirements 5.3**

Property 3: Multi User Mode allows non-localhost with authentication
*For any* host configuration value other than "127.0.0.1", when operating in Multi User Mode
with authentication enabled, the system should start successfully.
"""

from __future__ import annotations

import argparse

from hypothesis import given, settings
from hypothesis import strategies as st
from src.core.config.app_config import AppConfig
from src.core.config.models.access_mode import AccessMode, AccessModeConfig
from src.core.config.models.auth import AuthConfig
from src.core.config.models.notification import NotificationConfig
from src.core.services.access_mode_validator import AccessModeValidator

# Strategy for generating non-localhost IP addresses
non_localhost_ips = st.one_of(
    st.ip_addresses().filter(lambda ip: str(ip) != "127.0.0.1"),
    st.sampled_from(["0.0.0.0", "192.168.1.1", "10.0.0.1", "::1", "localhost"]),
)

# Strategy for generating API keys
api_key_strategy = st.text(min_size=1, max_size=100)


class TestMultiUserModeNonLocalhostWithAuthProperty:
    """Property tests for Multi User Mode non-localhost with authentication.

    **Validates: Requirements 5.3**
    """

    @given(host=non_localhost_ips, api_key=api_key_strategy)
    @settings(max_examples=50, deadline=None)
    def test_multi_user_mode_allows_non_localhost_with_api_key_auth(
        self, host: str, api_key: str
    ) -> None:
        """**Property 3**: Multi User Mode allows non-localhost with API key authentication.

        GIVEN a host address other than "127.0.0.1" and an API key
        WHEN operating in Multi User Mode with authentication enabled via API key
        THEN validation should pass
        """
        validator = AccessModeValidator()
        config = AppConfig(
            host=str(host),
            access_mode=AccessModeConfig(mode=AccessMode.MULTI_USER),
            auth=AuthConfig(disable_auth=False, api_keys=[api_key]),
            notifications=NotificationConfig(enabled=False),
        )
        args = argparse.Namespace()

        # Should not raise - validation should pass
        validator.validate(config, args)

    @given(host=non_localhost_ips)
    @settings(max_examples=50, deadline=None)
    def test_multi_user_mode_allows_non_localhost_with_sso_auth(
        self, host: str
    ) -> None:
        """**Property 3**: Multi User Mode allows non-localhost with SSO authentication.

        GIVEN a host address other than "127.0.0.1"
        WHEN operating in Multi User Mode with SSO enabled
        THEN validation should pass
        """
        from src.core.auth.sso.config import SSOConfig

        validator = AccessModeValidator()
        config = AppConfig(
            host=str(host),
            access_mode=AccessModeConfig(mode=AccessMode.MULTI_USER),
            auth=AuthConfig(disable_auth=True),  # Auth disabled but SSO enabled
            sso=SSOConfig(enabled=True),
            notifications=NotificationConfig(enabled=False),
        )
        args = argparse.Namespace()

        # Should not raise - validation should pass
        validator.validate(config, args)
