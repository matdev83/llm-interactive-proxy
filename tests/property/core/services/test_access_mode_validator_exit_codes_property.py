"""Property tests for validation exit codes.

**Feature: proxy-access-modes, Property 7: Validation failures exit with non-zero code**

**Validates: Requirements 11.4**

Property 7: Validation failures exit with non-zero code
*For any* validation failure, the system should exit with a non-zero exit code.

This property test verifies that all validation failures raise ValueError (which will be
caught by the CLI and result in non-zero exit).
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

# All OAuth debugging override flags
OAUTH_FLAGS = [
    "enable_gemini_oauth_auto_backend_debugging_override",
    "enable_gemini_oauth_free_backend_debugging_override",
    "enable_gemini_oauth_plan_backend_debugging_override",
    "enable_qwen_oauth_backend_debugging_override",
    "enable_anthropic_oauth_backend_debugging_override",
    "enable_opencode_zen_backend_debugging_override",
    "enable_kiro_oauth_auto_backend_debugging_override",
    "enable_openai_codex_backend_debugging_override",
]


class TestValidationExitCodesProperty:
    """Property tests for validation exit codes.

    **Validates: Requirements 11.4**
    """

    @given(host=non_localhost_ips)
    @settings(max_examples=50, deadline=None)
    def test_single_user_mode_validation_raises_value_error(self, host: str) -> None:
        """**Property 7**: Single User Mode validation failures raise ValueError.

        GIVEN an invalid Single User Mode configuration
        WHEN validation is called
        THEN ValueError should be raised (which results in non-zero exit code)
        """
        validator = AccessModeValidator()
        config = AppConfig(
            host=str(host),
            access_mode=AccessModeConfig(mode=AccessMode.SINGLE_USER),
            auth=AuthConfig(disable_auth=False),
            notifications=NotificationConfig(enabled=False),
        )
        args = argparse.Namespace()

        # Should raise ValueError (non-zero exit code)
        with pytest.raises(ValueError):
            validator.validate(config, args)

    @given(host=non_localhost_ips)
    @settings(max_examples=50, deadline=None)
    def test_multi_user_mode_auth_validation_raises_value_error(
        self, host: str
    ) -> None:
        """**Property 7**: Multi User Mode auth validation failures raise ValueError.

        GIVEN an invalid Multi User Mode authentication configuration
        WHEN validation is called
        THEN ValueError should be raised (which results in non-zero exit code)
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

        # Should raise ValueError (non-zero exit code)
        with pytest.raises(ValueError):
            validator.validate(config, args)

    @given(flag_name=st.sampled_from(OAUTH_FLAGS))
    @settings(max_examples=50, deadline=None)
    def test_multi_user_mode_oauth_flag_validation_raises_value_error(
        self, flag_name: str
    ) -> None:
        """**Property 7**: Multi User Mode OAuth flag validation failures raise ValueError.

        GIVEN an invalid Multi User Mode OAuth flag configuration
        WHEN validation is called
        THEN ValueError should be raised (which results in non-zero exit code)
        """
        validator = AccessModeValidator()
        config = AppConfig(
            host="127.0.0.1",
            access_mode=AccessModeConfig(mode=AccessMode.MULTI_USER),
            auth=AuthConfig(disable_auth=False),
            notifications=NotificationConfig(enabled=False),
        )
        args = argparse.Namespace(**{flag_name: True})

        # Should raise ValueError (non-zero exit code)
        with pytest.raises(ValueError):
            validator.validate(config, args)

    def test_multi_user_mode_oauth_auto_replacement_validation_raises_value_error(
        self,
    ) -> None:
        """**Property 7**: Multi User Mode OAuth auto-replacement validation raises ValueError.

        GIVEN an invalid Multi User Mode OAuth auto-replacement configuration
        WHEN validation is called
        THEN ValueError should be raised (which results in non-zero exit code)
        """
        validator = AccessModeValidator()
        config = AppConfig(
            host="127.0.0.1",
            access_mode=AccessModeConfig(mode=AccessMode.MULTI_USER),
            auth=AuthConfig(disable_auth=False),
            notifications=NotificationConfig(enabled=False),
        )
        args = argparse.Namespace(allow_oauth_auto_replacement=True)

        # Should raise ValueError (non-zero exit code)
        with pytest.raises(ValueError):
            validator.validate(config, args)

    def test_multi_user_mode_notification_validation_raises_value_error(
        self,
    ) -> None:
        """**Property 7**: Multi User Mode notification validation failures raise ValueError.

        GIVEN an invalid Multi User Mode notification configuration
        WHEN validation is called
        THEN ValueError should be raised (which results in non-zero exit code)
        """
        validator = AccessModeValidator()
        config = AppConfig(
            host="127.0.0.1",
            access_mode=AccessModeConfig(mode=AccessMode.MULTI_USER),
            auth=AuthConfig(disable_auth=False),
            notifications=NotificationConfig(enabled=True),
        )
        args = argparse.Namespace()

        # Should raise ValueError (non-zero exit code)
        with pytest.raises(ValueError):
            validator.validate(config, args)
