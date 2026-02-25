"""Integration tests for access mode startup validation.

Tests the integration of access mode validation with the application bootstrap,
ensuring that validation rules are enforced during proxy startup.

Requirements validated:
- 2.1-2.4: Single User Mode localhost enforcement
- 5.1-5.6: Multi User Mode authentication enforcement
- 7.1-7.4: Multi User Mode OAuth flag rejection
- 8.1-8.3: Multi User Mode OAuth auto-replacement rejection
- 9.1-9.5: Multi User Mode desktop notification rejection
- 11.1-11.4: Error messages and user guidance
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from src.core.cli_support.server_lifecycle_manager import ServerLifecycleManager
from src.core.config.app_config import AppConfig
from src.core.config.models.access_mode import AccessMode, AccessModeConfig
from src.core.config.models.auth import AuthConfig
from src.core.config.models.notification import NotificationConfig


@pytest.fixture
def mock_build_app():
    """Mock build_app_async to prevent full app initialization."""

    async def _mock_build_app(config: AppConfig) -> FastAPI:
        app = FastAPI()
        return app

    return _mock_build_app


@pytest.fixture
def mock_start_servers():
    """Mock start_servers to prevent actual server startup."""

    async def _mock_start_servers(app: FastAPI, cfg: AppConfig) -> None:
        pass

    return _mock_start_servers


@pytest.fixture
def mock_check_ports():
    """Mock check_ports to prevent port checking."""

    def _mock_check_ports(cfg: AppConfig) -> None:
        pass

    return _mock_check_ports


@pytest.fixture
def mock_args():
    """Create base mock args namespace."""
    import argparse

    args = argparse.Namespace()
    # Set all OAuth debugging override flags to False by default
    args.enable_gemini_oauth_auto_backend_debugging_override = False
    args.enable_gemini_oauth_free_backend_debugging_override = False
    args.enable_gemini_oauth_plan_backend_debugging_override = False
    args.enable_qwen_oauth_backend_debugging_override = False
    args.enable_anthropic_oauth_backend_debugging_override = False
    args.enable_openai_codex_backend_debugging_override = False
    args.enable_opencode_zen_backend_debugging_override = False
    args.enable_kiro_oauth_auto_backend_debugging_override = False
    args.allow_oauth_auto_replacement = False
    args.daemon = False
    args.allow_admin = False
    return args


class TestSingleUserModeStartup:
    """Tests for Single User Mode startup validation."""

    @pytest.mark.asyncio
    async def test_single_user_mode_succeeds_with_localhost(
        self, mock_build_app, mock_start_servers, mock_check_ports, mock_args
    ):
        """Test Single User Mode startup succeeds with localhost binding.

        Requirement 2.1: WHEN operating in Single User Mode and the host is set
        to 127.0.0.1 THEN the system SHALL start successfully.
        """
        cfg = AppConfig(
            host="127.0.0.1",
            port=8000,
            access_mode=AccessModeConfig(mode=AccessMode.SINGLE_USER),
            auth=AuthConfig(disable_auth=False),
            notifications=NotificationConfig(enabled=None),
        )

        manager = ServerLifecycleManager(build_app_async_fn=mock_build_app)

        with (
            patch.object(manager, "start_servers", mock_start_servers),
            patch.object(manager, "check_ports", mock_check_ports),
        ):
            # Should not raise
            await manager.run(mock_args, cfg)

    @pytest.mark.asyncio
    async def test_single_user_mode_succeeds_with_auth_enabled(
        self, mock_build_app, mock_start_servers, mock_check_ports, mock_args
    ):
        """Test Single User Mode startup succeeds with auth enabled.

        Requirement 4.2: WHEN operating in Single User Mode with authentication
        enabled THEN the system SHALL start successfully.
        """
        cfg = AppConfig(
            host="127.0.0.1",
            port=8000,
            access_mode=AccessModeConfig(mode=AccessMode.SINGLE_USER),
            auth=AuthConfig(disable_auth=False),  # Auth explicitly enabled
            notifications=NotificationConfig(enabled=None),
        )

        manager = ServerLifecycleManager(build_app_async_fn=mock_build_app)

        with (
            patch.object(manager, "start_servers", mock_start_servers),
            patch.object(manager, "check_ports", mock_check_ports),
        ):
            # Should not raise
            await manager.run(mock_args, cfg)

    @pytest.mark.asyncio
    async def test_single_user_mode_fails_with_non_localhost(
        self, mock_build_app, mock_start_servers, mock_check_ports, mock_args, capsys
    ):
        """Test Single User Mode startup fails with non-localhost binding.

        Requirements 2.2, 11.1-11.4: WHEN operating in Single User Mode and the
        host is set to any value other than 127.0.0.1 THEN the system SHALL
        refuse to start with a clear error message indicating that Single User
        Mode requires 127.0.0.1 binding and suggesting Multi User Mode for
        remote access.
        """
        cfg = AppConfig(
            host="0.0.0.0",
            port=8000,
            access_mode=AccessModeConfig(mode=AccessMode.SINGLE_USER),
            auth=AuthConfig(disable_auth=False),
            notifications=NotificationConfig(enabled=None),
        )

        manager = ServerLifecycleManager(build_app_async_fn=mock_build_app)

        with (
            patch.object(manager, "start_servers", mock_start_servers),
            patch.object(manager, "check_ports", mock_check_ports),
            pytest.raises(SystemExit) as exc_info,
        ):
            await manager.run(mock_args, cfg)

        # Verify exit code (Requirement 11.4)
        assert exc_info.value.code == 1

        # Capture and verify error message (Requirements 11.1-11.3)
        captured = capsys.readouterr()
        error_output = captured.err

        # Requirement 11.1: Specific validation failure
        assert "Single User Mode requires binding to 127.0.0.1 only" in error_output

        # Requirement 11.2: Actionable guidance
        assert "Current host: 0.0.0.0" in error_output

        # Requirement 11.3: Reference CLI flags
        assert "--multi-user-mode" in error_output


class TestMultiUserModeStartup:
    """Tests for Multi User Mode startup validation."""

    @pytest.mark.asyncio
    async def test_multi_user_mode_succeeds_with_localhost_no_auth(
        self, mock_build_app, mock_start_servers, mock_check_ports, mock_args
    ):
        """Test Multi User Mode startup succeeds with localhost and no auth.

        Requirement 5.1: WHEN operating in Multi User Mode and the host is set
        to 127.0.0.1 with authentication disabled THEN the system SHALL start
        successfully.
        """
        cfg = AppConfig(
            host="127.0.0.1",
            port=8000,
            access_mode=AccessModeConfig(mode=AccessMode.MULTI_USER),
            auth=AuthConfig(disable_auth=True),
            notifications=NotificationConfig(enabled=False),
        )

        manager = ServerLifecycleManager(build_app_async_fn=mock_build_app)

        with (
            patch.object(manager, "start_servers", mock_start_servers),
            patch.object(manager, "check_ports", mock_check_ports),
        ):
            # Should not raise
            await manager.run(mock_args, cfg)

    @pytest.mark.asyncio
    async def test_multi_user_mode_succeeds_with_localhost_and_auth(
        self, mock_build_app, mock_start_servers, mock_check_ports, mock_args
    ):
        """Test Multi User Mode startup succeeds with localhost and auth.

        Requirement 5.2: WHEN operating in Multi User Mode and the host is set
        to 127.0.0.1 with authentication enabled THEN the system SHALL start
        successfully.
        """
        cfg = AppConfig(
            host="127.0.0.1",
            port=8000,
            access_mode=AccessModeConfig(mode=AccessMode.MULTI_USER),
            auth=AuthConfig(disable_auth=False),  # Auth enabled
            notifications=NotificationConfig(enabled=False),
        )

        manager = ServerLifecycleManager(build_app_async_fn=mock_build_app)

        with (
            patch.object(manager, "start_servers", mock_start_servers),
            patch.object(manager, "check_ports", mock_check_ports),
        ):
            # Should not raise
            await manager.run(mock_args, cfg)

    @pytest.mark.asyncio
    async def test_multi_user_mode_succeeds_with_non_localhost_and_auth(
        self, mock_build_app, mock_start_servers, mock_check_ports, mock_args
    ):
        """Test Multi User Mode startup succeeds with non-localhost and auth.

        Requirement 5.3: WHEN operating in Multi User Mode and the host is set
        to any value other than 127.0.0.1 with authentication enabled THEN the
        system SHALL start successfully.
        """
        cfg = AppConfig(
            host="0.0.0.0",
            port=8000,
            access_mode=AccessModeConfig(mode=AccessMode.MULTI_USER),
            auth=AuthConfig(disable_auth=False),  # Auth enabled
            notifications=NotificationConfig(enabled=False),
        )

        manager = ServerLifecycleManager(build_app_async_fn=mock_build_app)

        with (
            patch.object(manager, "start_servers", mock_start_servers),
            patch.object(manager, "check_ports", mock_check_ports),
        ):
            # Should not raise
            await manager.run(mock_args, cfg)

    @pytest.mark.asyncio
    async def test_multi_user_mode_fails_with_non_localhost_without_auth(
        self, mock_build_app, mock_start_servers, mock_check_ports, mock_args, capsys
    ):
        """Test Multi User Mode startup fails with non-localhost without auth.

        Requirements 5.4, 11.1-11.4: WHEN operating in Multi User Mode and the
        host is set to any value other than 127.0.0.1 with authentication
        disabled THEN the system SHALL refuse to start with a clear error
        message indicating that Multi User Mode requires authentication for
        non-localhost binding and which authentication methods are available.
        """
        cfg = AppConfig(
            host="0.0.0.0",
            port=8000,
            access_mode=AccessModeConfig(mode=AccessMode.MULTI_USER),
            auth=AuthConfig(disable_auth=True),  # Auth disabled
            notifications=NotificationConfig(enabled=False),
        )

        manager = ServerLifecycleManager(build_app_async_fn=mock_build_app)

        with (
            patch.object(manager, "start_servers", mock_start_servers),
            patch.object(manager, "check_ports", mock_check_ports),
            pytest.raises(SystemExit) as exc_info,
        ):
            await manager.run(mock_args, cfg)

        # Verify exit code (Requirement 11.4)
        assert exc_info.value.code == 1

        # Capture and verify error message (Requirements 11.1-11.3)
        captured = capsys.readouterr()
        error_output = captured.err

        # Requirement 11.1: Specific validation failure
        assert (
            "Multi User Mode requires authentication when binding to non-localhost addresses"
            in error_output
        )

        # Requirement 11.2: Actionable guidance (show current host and auth methods)
        assert "Current host: 0.0.0.0" in error_output
        assert "API keys" in error_output or "SSO" in error_output

        # Requirement 11.3: Reference CLI flags
        assert "--api-key" in error_output or "authentication" in error_output


class TestMultiUserModeOAuthRestrictions:
    """Tests for Multi User Mode OAuth-related restrictions."""

    @pytest.mark.asyncio
    async def test_multi_user_mode_fails_with_oauth_debugging_flags(
        self, mock_build_app, mock_start_servers, mock_check_ports, mock_args, capsys
    ):
        """Test Multi User Mode startup fails with OAuth debugging override flags.

        Requirements 7.1, 11.1-11.4: WHEN operating in Multi User Mode and any
        OAuth debugging override flag is specified THEN the system SHALL refuse
        to start with a clear error message listing the conflicting flags and
        indicating that OAuth connectors are not allowed in Multi User Mode.
        """
        cfg = AppConfig(
            host="127.0.0.1",
            port=8000,
            access_mode=AccessModeConfig(mode=AccessMode.MULTI_USER),
            auth=AuthConfig(disable_auth=False),
            notifications=NotificationConfig(enabled=False),
        )

        # Set OAuth debugging override flag
        mock_args.enable_gemini_oauth_auto_backend_debugging_override = True

        manager = ServerLifecycleManager(build_app_async_fn=mock_build_app)

        with (
            patch.object(manager, "start_servers", mock_start_servers),
            patch.object(manager, "check_ports", mock_check_ports),
            pytest.raises(SystemExit) as exc_info,
        ):
            await manager.run(mock_args, cfg)

        # Verify exit code (Requirement 11.4)
        assert exc_info.value.code == 1

        # Capture and verify error message (Requirements 11.1-11.3)
        captured = capsys.readouterr()
        error_output = captured.err

        # Requirement 11.1: Specific validation failure
        assert (
            "OAuth debugging override flags are not allowed in Multi User Mode"
            in error_output
        )

        # Requirement 11.2: Actionable guidance (list conflicting flags)
        assert "--enable-gemini-oauth-auto-backend-debugging-override" in error_output

        # Requirement 11.3: OAuth connectors blocked in production
        assert "OAuth connectors are blocked in production deployments" in error_output

    @pytest.mark.asyncio
    async def test_multi_user_mode_fails_with_oauth_auto_replacement(
        self, mock_build_app, mock_start_servers, mock_check_ports, mock_args, capsys
    ):
        """Test Multi User Mode startup fails with OAuth auto-replacement flag.

        Requirements 8.1, 11.1-11.4: WHEN operating in Multi User Mode and the
        --allow-oauth-auto-replacement flag is specified THEN the system SHALL
        refuse to start with a clear error message indicating that OAuth auto-
        replacement is not allowed in Multi User Mode.
        """
        cfg = AppConfig(
            host="127.0.0.1",
            port=8000,
            access_mode=AccessModeConfig(mode=AccessMode.MULTI_USER),
            auth=AuthConfig(disable_auth=False),
            notifications=NotificationConfig(enabled=False),
        )

        # Set OAuth auto-replacement flag
        mock_args.allow_oauth_auto_replacement = True

        manager = ServerLifecycleManager(build_app_async_fn=mock_build_app)

        with (
            patch.object(manager, "start_servers", mock_start_servers),
            patch.object(manager, "check_ports", mock_check_ports),
            pytest.raises(SystemExit) as exc_info,
        ):
            await manager.run(mock_args, cfg)

        # Verify exit code (Requirement 11.4)
        assert exc_info.value.code == 1

        # Capture and verify error message (Requirements 11.1-11.3)
        captured = capsys.readouterr()
        error_output = captured.err

        # Requirement 11.1: Specific validation failure
        assert "OAuth auto-replacement" in error_output
        assert "not allowed in Multi User Mode" in error_output

        # Requirement 11.2: Actionable guidance
        assert "--allow-oauth-auto-replacement" in error_output

        # Requirement 11.3: OAuth connectors blocked in production
        assert "OAuth connectors are blocked in production deployments" in error_output

    @pytest.mark.asyncio
    async def test_multi_user_mode_fails_with_notifications(
        self, mock_build_app, mock_start_servers, mock_check_ports, mock_args, capsys
    ):
        """Test Multi User Mode startup fails with desktop notifications enabled.

        Requirements 9.1, 11.1-11.4: WHEN operating in Multi User Mode and
        desktop notifications are enabled THEN the system SHALL refuse to start
        with a clear error message indicating that desktop notifications are
        only supported in Single User Mode and that Multi User Mode is for
        dedicated servers.
        """
        cfg = AppConfig(
            host="127.0.0.1",
            port=8000,
            access_mode=AccessModeConfig(mode=AccessMode.MULTI_USER),
            auth=AuthConfig(disable_auth=False),
            notifications=NotificationConfig(enabled=True),  # Enabled
        )

        manager = ServerLifecycleManager(build_app_async_fn=mock_build_app)

        with (
            patch.object(manager, "start_servers", mock_start_servers),
            patch.object(manager, "check_ports", mock_check_ports),
            pytest.raises(SystemExit) as exc_info,
        ):
            await manager.run(mock_args, cfg)

        # Verify exit code (Requirement 11.4)
        assert exc_info.value.code == 1

        # Capture and verify error message (Requirements 11.1-11.3)
        captured = capsys.readouterr()
        error_output = captured.err

        # Requirement 11.1: Specific validation failure
        assert (
            "Desktop notifications are not allowed in Multi User Mode" in error_output
        )

        # Requirement 11.2: Actionable guidance
        assert "Multi User Mode is for dedicated servers" in error_output

        # Requirement 11.3: Reference CLI flags
        assert (
            "--disable-notifications" in error_output
            or "Single User Mode" in error_output
        )
