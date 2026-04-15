"""Unit tests for AccessModeValidator.

Tests access mode validation rules covering:
- Single User Mode localhost enforcement
- Single User Mode OAuth flags and notifications support
- Multi User Mode authentication enforcement
- Multi User Mode OAuth flag rejection
- Multi User Mode OAuth auto-replacement rejection
- Multi User Mode desktop notification rejection
- Error message quality and guidance

Requirements satisfied:
- 2.1-2.4: Single User Mode localhost enforcement
- 4.1-4.3: Single User Mode optional authentication
- 5.1-5.6: Multi User Mode authentication enforcement
- 7.1-7.4: Multi User Mode OAuth flag rejection
- 8.1-8.3: Multi User Mode OAuth auto-replacement rejection
- 9.1-9.5: Multi User Mode desktop notification rejection
- 11.1-11.4: Error messages and user guidance
"""

from __future__ import annotations

import argparse

import pytest
from src.core.config.app_config import AppConfig
from src.core.config.models.access_mode import AccessMode, AccessModeConfig
from src.core.config.models.auth import AuthConfig
from src.core.config.models.notification import NotificationConfig
from src.core.services.access_mode_validator import AccessModeValidator


@pytest.fixture
def validator():
    """Create AccessModeValidator instance."""
    return AccessModeValidator()


@pytest.fixture
def empty_args():
    """Create empty argparse.Namespace."""
    return argparse.Namespace()


@pytest.fixture
def single_user_config():
    """Create AppConfig with Single User Mode."""
    return AppConfig(
        host="127.0.0.1",
        access_mode=AccessModeConfig(mode=AccessMode.SINGLE_USER),
        auth=AuthConfig(disable_auth=False),
        notifications=NotificationConfig(enabled=None),
    )


@pytest.fixture
def multi_user_config():
    """Create AppConfig with Multi User Mode."""
    return AppConfig(
        host="127.0.0.1",
        access_mode=AccessModeConfig(mode=AccessMode.MULTI_USER),
        auth=AuthConfig(disable_auth=False),
        notifications=NotificationConfig(
            enabled=False
        ),  # Explicitly disabled for Multi User Mode
    )


class TestSingleUserModeLocalhost:
    """Tests for Single User Mode localhost enforcement."""

    def test_single_user_mode_allows_localhost(
        self, validator: AccessModeValidator, single_user_config: AppConfig, empty_args
    ):
        """Test Single User Mode allows localhost binding."""
        # Should not raise
        validator.validate(single_user_config, empty_args)

    def test_single_user_mode_rejects_non_localhost(
        self, validator: AccessModeValidator, single_user_config: AppConfig, empty_args
    ):
        """Test Single User Mode rejects non-localhost binding."""
        single_user_config.host = "0.0.0.0"

        with pytest.raises(ValueError) as exc_info:
            validator.validate(single_user_config, empty_args)

        error_msg = str(exc_info.value)
        assert "Single User Mode requires binding to 127.0.0.1 only" in error_msg
        assert "Current host: 0.0.0.0" in error_msg
        assert "--multi-user-mode" in error_msg

    def test_single_user_mode_rejects_other_ips(
        self, validator: AccessModeValidator, single_user_config: AppConfig, empty_args
    ):
        """Test Single User Mode rejects various non-localhost IPs."""
        for host in ["192.168.1.1", "10.0.0.1", "::1", "localhost"]:
            single_user_config.host = host

            with pytest.raises(ValueError) as exc_info:
                validator.validate(single_user_config, empty_args)

            error_msg = str(exc_info.value)
            assert "Single User Mode requires binding to 127.0.0.1 only" in error_msg
            assert f"Current host: {host}" in error_msg


class TestSingleUserModeOAuthSupport:
    """Tests for Single User Mode OAuth flags support."""

    def test_single_user_mode_allows_oauth_flags(
        self, validator: AccessModeValidator, single_user_config: AppConfig
    ):
        """Test Single User Mode allows OAuth debugging override flags."""
        args = argparse.Namespace(
            enable_gemini_oauth_auto_backend_debugging_override=True,
            enable_gemini_oauth_free_backend_debugging_override=True,
            enable_gemini_oauth_plan_backend_debugging_override=True,
            enable_qwen_oauth_backend_debugging_override=True,
            enable_openai_codex_backend_debugging_override=True,
        )

        # Should not raise
        validator.validate(single_user_config, args)

    def test_single_user_mode_allows_oauth_auto_replacement(
        self, validator: AccessModeValidator, single_user_config: AppConfig
    ):
        """Test Single User Mode allows OAuth auto-replacement flag."""
        args = argparse.Namespace(allow_oauth_auto_replacement=True)

        # Should not raise
        validator.validate(single_user_config, args)

    def test_single_user_mode_allows_notifications(
        self, validator: AccessModeValidator, single_user_config: AppConfig, empty_args
    ):
        """Test Single User Mode allows desktop notifications."""
        single_user_config.notifications = NotificationConfig(enabled=True)

        # Should not raise
        validator.validate(single_user_config, empty_args)


class TestMultiUserModeAuthentication:
    """Tests for Multi User Mode authentication enforcement."""

    def test_multi_user_mode_allows_localhost_without_auth(
        self, validator: AccessModeValidator, multi_user_config: AppConfig, empty_args
    ):
        """Test Multi User Mode allows localhost without authentication."""
        multi_user_config.auth = AuthConfig(disable_auth=True)

        # Should not raise
        validator.validate(multi_user_config, empty_args)

    def test_multi_user_mode_allows_localhost_with_auth(
        self, validator: AccessModeValidator, multi_user_config: AppConfig, empty_args
    ):
        """Test Multi User Mode allows localhost with authentication."""
        multi_user_config.auth = AuthConfig(disable_auth=False, api_keys=["test_key"])

        # Should not raise
        validator.validate(multi_user_config, empty_args)

    def test_multi_user_mode_allows_non_localhost_with_auth(
        self, validator: AccessModeValidator, multi_user_config: AppConfig, empty_args
    ):
        """Test Multi User Mode allows non-localhost with authentication."""
        multi_user_config.host = "0.0.0.0"
        multi_user_config.auth = AuthConfig(disable_auth=False, api_keys=["test_key"])

        # Should not raise
        validator.validate(multi_user_config, empty_args)

    def test_multi_user_mode_allows_non_localhost_with_sso(
        self, validator: AccessModeValidator, multi_user_config: AppConfig, empty_args
    ):
        """Test Multi User Mode allows non-localhost with SSO enabled."""
        from src.core.auth.sso.config import SSOConfig

        multi_user_config.host = "0.0.0.0"
        multi_user_config.auth = AuthConfig(disable_auth=True)
        multi_user_config.sso = SSOConfig(enabled=True)

        # Should not raise
        validator.validate(multi_user_config, empty_args)

    def test_multi_user_mode_rejects_non_localhost_without_auth(
        self, validator: AccessModeValidator, multi_user_config: AppConfig, empty_args
    ):
        """Test Multi User Mode rejects non-localhost without authentication."""
        multi_user_config.host = "0.0.0.0"
        multi_user_config.auth = AuthConfig(disable_auth=True)
        multi_user_config.sso = None

        with pytest.raises(ValueError) as exc_info:
            validator.validate(multi_user_config, empty_args)

        error_msg = str(exc_info.value)
        assert (
            "Multi User Mode requires authentication when binding to non-localhost"
            in error_msg
        )
        assert "Current host: 0.0.0.0" in error_msg
        assert "--api-key" in error_msg or "SSO" in error_msg


class TestMultiUserModeOAuthFlags:
    """Tests for Multi User Mode OAuth flag rejection."""

    @pytest.mark.parametrize(
        "flag_name",
        [
            "enable_gemini_oauth_auto_backend_debugging_override",
            "enable_gemini_oauth_free_backend_debugging_override",
            "enable_gemini_oauth_plan_backend_debugging_override",
            "enable_qwen_oauth_backend_debugging_override",
            "enable_opencode_zen_backend_debugging_override",
            "enable_kiro_oauth_auto_backend_debugging_override",
            "enable_openai_codex_backend_debugging_override",
        ],
    )
    def test_multi_user_mode_rejects_each_oauth_flag(
        self,
        validator: AccessModeValidator,
        multi_user_config: AppConfig,
        flag_name: str,
    ):
        """Test Multi User Mode rejects each OAuth debugging override flag."""
        args = argparse.Namespace(**{flag_name: True})

        with pytest.raises(ValueError) as exc_info:
            validator.validate(multi_user_config, args)

        error_msg = str(exc_info.value)
        assert (
            "OAuth debugging override flags are not allowed in Multi User Mode"
            in error_msg
        )
        assert "OAuth connectors are blocked in production deployments" in error_msg

    def test_multi_user_mode_rejects_multiple_oauth_flags(
        self, validator: AccessModeValidator, multi_user_config: AppConfig
    ):
        """Test Multi User Mode rejects multiple OAuth flags at once."""
        args = argparse.Namespace(
            enable_gemini_oauth_auto_backend_debugging_override=True,
            enable_qwen_oauth_backend_debugging_override=True,
        )

        with pytest.raises(ValueError) as exc_info:
            validator.validate(multi_user_config, args)

        error_msg = str(exc_info.value)
        assert (
            "OAuth debugging override flags are not allowed in Multi User Mode"
            in error_msg
        )

    def test_multi_user_mode_rejects_opencode_zen_flag(
        self, validator: AccessModeValidator, multi_user_config: AppConfig
    ):
        """Test Multi User Mode specifically rejects opencode-zen OAuth flag."""
        args = argparse.Namespace(enable_opencode_zen_backend_debugging_override=True)

        with pytest.raises(ValueError) as exc_info:
            validator.validate(multi_user_config, args)

        error_msg = str(exc_info.value)
        assert (
            "OAuth debugging override flags are not allowed in Multi User Mode"
            in error_msg
        )
        assert "--enable-opencode-zen-backend-debugging-override" in error_msg
        assert "OAuth connectors are blocked in production deployments" in error_msg

    def test_multi_user_mode_rejects_kiro_oauth_auto_flag(
        self, validator: AccessModeValidator, multi_user_config: AppConfig
    ):
        """Test Multi User Mode specifically rejects kiro-oauth-auto OAuth flag."""
        args = argparse.Namespace(
            enable_kiro_oauth_auto_backend_debugging_override=True
        )

        with pytest.raises(ValueError) as exc_info:
            validator.validate(multi_user_config, args)

        error_msg = str(exc_info.value)
        assert (
            "OAuth debugging override flags are not allowed in Multi User Mode"
            in error_msg
        )
        assert "--enable-kiro-oauth-auto-backend-debugging-override" in error_msg
        assert "OAuth connectors are blocked in production deployments" in error_msg


class TestMultiUserModeOAuthAutoReplacement:
    """Tests for Multi User Mode OAuth auto-replacement rejection."""

    def test_multi_user_mode_rejects_oauth_auto_replacement(
        self, validator: AccessModeValidator, multi_user_config: AppConfig
    ):
        """Test Multi User Mode rejects OAuth auto-replacement flag."""
        args = argparse.Namespace(allow_oauth_auto_replacement=True)

        with pytest.raises(ValueError) as exc_info:
            validator.validate(multi_user_config, args)

        error_msg = str(exc_info.value)
        assert "--allow-oauth-auto-replacement" in error_msg
        assert "is not allowed in Multi User Mode" in error_msg
        assert "OAuth connectors are blocked in production deployments" in error_msg


class TestMultiUserModeNotifications:
    """Tests for Multi User Mode desktop notification rejection."""

    def test_multi_user_mode_rejects_notifications(
        self, validator: AccessModeValidator, multi_user_config: AppConfig, empty_args
    ):
        """Test Multi User Mode rejects desktop notifications."""
        multi_user_config.notifications = NotificationConfig(enabled=True)

        with pytest.raises(ValueError) as exc_info:
            validator.validate(multi_user_config, empty_args)

        error_msg = str(exc_info.value)
        assert "Desktop notifications are not allowed in Multi User Mode" in error_msg
        assert "--disable-notifications" in error_msg or "Single User Mode" in error_msg
        assert "dedicated servers" in error_msg or "desktop computers" in error_msg


class TestErrorMessageQuality:
    """Tests for error message quality and guidance."""

    def test_error_messages_contain_actionable_guidance(
        self, validator: AccessModeValidator, single_user_config: AppConfig, empty_args
    ):
        """Test error messages contain actionable guidance."""
        single_user_config.host = "0.0.0.0"

        with pytest.raises(ValueError) as exc_info:
            validator.validate(single_user_config, empty_args)

        error_msg = str(exc_info.value)
        # Check for guidance keywords
        assert any(
            keyword in error_msg.lower()
            for keyword in ["use", "enable", "switch", "disable", "set"]
        )

    def test_error_messages_reference_cli_flags(
        self, validator: AccessModeValidator, multi_user_config: AppConfig
    ):
        """Test error messages reference relevant CLI flags."""
        args = argparse.Namespace(allow_oauth_auto_replacement=True)

        with pytest.raises(ValueError) as exc_info:
            validator.validate(multi_user_config, args)

        error_msg = str(exc_info.value)
        # Should contain at least one CLI flag reference
        assert "--" in error_msg

    def test_error_messages_show_current_values(
        self, validator: AccessModeValidator, single_user_config: AppConfig, empty_args
    ):
        """Test error messages show current configuration values."""
        single_user_config.host = "192.168.1.100"

        with pytest.raises(ValueError) as exc_info:
            validator.validate(single_user_config, empty_args)

        error_msg = str(exc_info.value)
        assert "Current host: 192.168.1.100" in error_msg
