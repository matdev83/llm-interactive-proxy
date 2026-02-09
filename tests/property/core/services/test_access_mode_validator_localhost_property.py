"""Property tests for Single User Mode localhost enforcement.

**Feature: proxy-access-modes, Property 1: Single User Mode localhost enforcement**

**Validates: Requirements 2.2**

Property 1: Single User Mode localhost enforcement
*For any* host configuration value other than "127.0.0.1", when operating in Single User Mode,
the system should refuse to start with a validation error.
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
    st.sampled_from(
        ["0.0.0.0", "192.168.1.1", "10.0.0.1", "::1", "localhost", "0.0.0.0"]
    ),
)


class TestSingleUserModeLocalhostEnforcementProperty:
    """Property tests for Single User Mode localhost enforcement.

    **Validates: Requirements 2.2**
    """

    @given(host=non_localhost_ips)
    @settings(max_examples=50, deadline=None)
    def test_single_user_mode_rejects_non_localhost(self, host: str) -> None:
        """**Property 1**: Single User Mode rejects any non-localhost host.

        GIVEN a host address other than "127.0.0.1"
        WHEN operating in Single User Mode
        THEN validation should raise ValueError
        """
        validator = AccessModeValidator()
        config = AppConfig(
            host=str(host),
            access_mode=AccessModeConfig(mode=AccessMode.SINGLE_USER),
            auth=AuthConfig(disable_auth=False),
            notifications=NotificationConfig(enabled=False),
        )
        args = argparse.Namespace()

        # Should raise ValueError for any non-localhost address
        with pytest.raises(ValueError) as exc_info:
            validator.validate(config, args)

        error_msg = str(exc_info.value)
        assert "Single User Mode requires binding to 127.0.0.1 only" in error_msg
        assert f"Current host: {host}" in error_msg
        assert "--multi-user-mode" in error_msg
