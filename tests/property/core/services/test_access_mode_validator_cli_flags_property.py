"""Property tests for error message CLI flag references.

**Feature: proxy-access-modes, Property 6: Error messages reference relevant CLI flags**

**Validates: Requirements 11.3**

Property 6: Error messages reference relevant CLI flags
*For any* access mode validation failure, the error message should reference
the relevant CLI flags or configuration options.
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


class TestErrorMessageCliFlagsProperty:
    """Property tests for error message CLI flag references.

    **Validates: Requirements 11.3**
    """

    @given(host=non_localhost_ips)
    @settings(max_examples=50, deadline=None)
    def test_single_user_mode_error_references_cli_flags(self, host: str) -> None:
        """**Property 6**: Single User Mode error messages reference CLI flags.

        GIVEN a Single User Mode validation failure
        WHEN validation raises ValueError
        THEN the error message should contain at least one CLI flag reference (--flag)
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

        error_msg = str(exc_info.value)
        # Should contain at least one CLI flag reference (starts with --)
        assert (
            "--" in error_msg
        ), f"Error message should reference CLI flags. Message: {error_msg}"

    @given(host=non_localhost_ips)
    @settings(max_examples=50, deadline=None)
    def test_multi_user_mode_auth_error_references_cli_flags(self, host: str) -> None:
        """**Property 6**: Multi User Mode auth error messages reference CLI flags.

        GIVEN a Multi User Mode authentication validation failure
        WHEN validation raises ValueError
        THEN the error message should contain at least one CLI flag reference (--flag)
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

        error_msg = str(exc_info.value)
        # Should contain at least one CLI flag reference (starts with --)
        assert (
            "--" in error_msg
        ), f"Error message should reference CLI flags. Message: {error_msg}"

    def test_multi_user_mode_oauth_flag_error_references_cli_flags(self) -> None:
        """**Property 6**: Multi User Mode OAuth flag error messages reference CLI flags.

        GIVEN a Multi User Mode OAuth flag validation failure
        WHEN validation raises ValueError
        THEN the error message should contain at least one CLI flag reference (--flag)
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

        error_msg = str(exc_info.value)
        # Should contain at least one CLI flag reference (starts with --)
        assert (
            "--" in error_msg
        ), f"Error message should reference CLI flags. Message: {error_msg}"

    def test_multi_user_mode_oauth_auto_replacement_error_references_cli_flags(
        self,
    ) -> None:
        """**Property 6**: Multi User Mode OAuth auto-replacement error references CLI flags.

        GIVEN a Multi User Mode OAuth auto-replacement validation failure
        WHEN validation raises ValueError
        THEN the error message should contain at least one CLI flag reference (--flag)
        """
        validator = AccessModeValidator()
        config = AppConfig(
            host="127.0.0.1",
            access_mode=AccessModeConfig(mode=AccessMode.MULTI_USER),
            auth=AuthConfig(disable_auth=False),
            notifications=NotificationConfig(enabled=False),
        )
        args = argparse.Namespace(allow_oauth_auto_replacement=True)

        with pytest.raises(ValueError) as exc_info:
            validator.validate(config, args)

        error_msg = str(exc_info.value)
        # Should contain at least one CLI flag reference (starts with --)
        assert (
            "--" in error_msg
        ), f"Error message should reference CLI flags. Message: {error_msg}"

    def test_multi_user_mode_notification_error_references_cli_flags(self) -> None:
        """**Property 6**: Multi User Mode notification error messages reference CLI flags.

        GIVEN a Multi User Mode notification validation failure
        WHEN validation raises ValueError
        THEN the error message should contain at least one CLI flag reference (--flag)
        """
        validator = AccessModeValidator()
        config = AppConfig(
            host="127.0.0.1",
            access_mode=AccessModeConfig(mode=AccessMode.MULTI_USER),
            auth=AuthConfig(disable_auth=False),
            notifications=NotificationConfig(enabled=True),
        )
        args = argparse.Namespace()

        with pytest.raises(ValueError) as exc_info:
            validator.validate(config, args)

        error_msg = str(exc_info.value)
        # Should contain at least one CLI flag reference (starts with --)
        assert (
            "--" in error_msg
        ), f"Error message should reference CLI flags. Message: {error_msg}"
