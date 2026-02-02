"""Property tests for Multi User Mode authentication enforcement.

**Feature: proxy-access-modes, Property 2: Multi User Mode authentication enforcement**

**Validates: Requirements 5.4**

Property 2: Multi User Mode authentication enforcement for non-localhost
*For any* host configuration value other than "127.0.0.1", when operating in Multi User Mode
with authentication disabled, the system should refuse to start with a validation error.
"""

from __future__ import annotations

import argparse

import pytest
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


class TestMultiUserModeAuthEnforcementProperty:
    """Property tests for Multi User Mode authentication enforcement.

    **Validates: Requirements 5.4**
    """

    @given(host=non_localhost_ips)
    @settings(max_examples=50, deadline=None)
    def test_multi_user_mode_rejects_non_localhost_without_auth(
        self, host: str
    ) -> None:
        """**Property 2**: Multi User Mode rejects non-localhost without authentication.

        GIVEN a host address other than "127.0.0.1"
        WHEN operating in Multi User Mode with authentication disabled
        THEN validation should raise ValueError
        """
        validator = AccessModeValidator()
        config = AppConfig(
            host=str(host),
            access_mode=AccessModeConfig(mode=AccessMode.MULTI_USER),
            auth=AuthConfig(disable_auth=True),  # Auth disabled
            sso=None,  # No SSO
            notifications=NotificationConfig(enabled=False),
        )
        args = argparse.Namespace()

        # Should raise ValueError for non-localhost without auth
        with pytest.raises(ValueError) as exc_info:
            validator.validate(config, args)

        error_msg = str(exc_info.value)
        assert (
            "Multi User Mode requires authentication when binding to non-localhost"
            in error_msg
        )
        assert f"Current host: {host}" in error_msg
        assert "--api-key" in error_msg or "SSO" in error_msg
