"""Property tests for error message guidance quality.

**Feature: proxy-access-modes, Property 5: Error messages provide actionable guidance**

**Validates: Requirements 11.2**

Property 5: Error messages provide actionable guidance
*For any* validation failure, the error message should contain actionable guidance
on how to resolve the issue.
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
    st.sampled_from(["0.0.0.0", "192.168.1.1", "10.0.0.1"]),
)

# Guidance keywords that should appear in error messages
GUIDANCE_KEYWORDS = [
    "use",
    "enable",
    "switch",
    "disable",
    "set",
    "configure",
    "add",
    "remove",
]


class TestErrorMessageGuidanceProperty:
    """Property tests for error message guidance quality.

    **Validates: Requirements 11.2**
    """

    @given(host=non_localhost_ips)
    @settings(max_examples=50, deadline=None)
    def test_single_user_mode_error_contains_guidance(self, host: str) -> None:
        """**Property 5**: Single User Mode error messages contain actionable guidance.

        GIVEN a Single User Mode validation failure
        WHEN validation raises ValueError
        THEN the error message should contain guidance keywords
        """
        validator = AccessModeValidator()
        config = AppConfig(
            host=str(host),
            access_mode=AccessModeConfig(mode=AccessMode.SINGLE_USER),
            auth=AuthConfig(disable_auth=False),
            notifications=NotificationConfig(enabled=False),
        )
        args = argparse.Namespace()

        with pytest.raises(ValueError) as exc_info:
            validator.validate(config, args)

        error_msg = str(exc_info.value).lower()
        # Check that at least one guidance keyword appears
        assert any(
            keyword in error_msg for keyword in GUIDANCE_KEYWORDS
        ), f"Error message should contain guidance keywords. Message: {error_msg}"

    @given(host=non_localhost_ips)
    @settings(max_examples=50, deadline=None)
    def test_multi_user_mode_auth_error_contains_guidance(self, host: str) -> None:
        """**Property 5**: Multi User Mode auth error messages contain actionable guidance.

        GIVEN a Multi User Mode authentication validation failure
        WHEN validation raises ValueError
        THEN the error message should contain guidance keywords
        """
        validator = AccessModeValidator()
        config = AppConfig(
            host=str(host),
            access_mode=AccessModeConfig(mode=AccessMode.MULTI_USER),
            auth=AuthConfig(disable_auth=True),
            sso=None,
            notifications=NotificationConfig(enabled=False),
        )
        args = argparse.Namespace()

        with pytest.raises(ValueError) as exc_info:
            validator.validate(config, args)

        error_msg = str(exc_info.value).lower()
        # Check that at least one guidance keyword appears
        assert any(
            keyword in error_msg for keyword in GUIDANCE_KEYWORDS
        ), f"Error message should contain guidance keywords. Message: {error_msg}"

    def test_multi_user_mode_oauth_flag_error_contains_guidance(self) -> None:
        """**Property 5**: Multi User Mode OAuth flag error messages contain actionable guidance.

        GIVEN a Multi User Mode OAuth flag validation failure
        WHEN validation raises ValueError
        THEN the error message should contain guidance keywords
        """
        validator = AccessModeValidator()
        config = AppConfig(
            host="127.0.0.1",
            access_mode=AccessModeConfig(mode=AccessMode.MULTI_USER),
            auth=AuthConfig(disable_auth=False),
            notifications=NotificationConfig(enabled=False),
        )
        args = argparse.Namespace(
            enable_gemini_oauth_auto_backend_debugging_override=True
        )

        with pytest.raises(ValueError) as exc_info:
            validator.validate(config, args)

        error_msg = str(exc_info.value).lower()
        # Check that at least one guidance keyword appears
        assert any(
            keyword in error_msg for keyword in GUIDANCE_KEYWORDS
        ), f"Error message should contain guidance keywords. Message: {error_msg}"
