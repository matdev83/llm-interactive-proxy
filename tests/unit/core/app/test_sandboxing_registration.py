"""Tests for sandboxing handler registration in application builder."""

import logging
from unittest.mock import Mock

import pytest
from src.core.app.application_builder import _register_sandboxing_handler
from src.core.config.app_config import AppConfig
from src.core.domain.configuration.sandboxing_config import SandboxingConfiguration
from src.core.interfaces.di_interface import IServiceProvider


class TestSandboxingHandlerRegistration:
    """Test the _register_sandboxing_handler function."""

    def test_registration_skipped_when_disabled(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that registration is skipped when sandboxing is disabled."""
        config = AppConfig(sandboxing=SandboxingConfiguration(enabled=False))
        service_provider = Mock(spec=IServiceProvider)

        with caplog.at_level(logging.INFO):
            _register_sandboxing_handler(config, service_provider)

        assert "File access sandboxing: DISABLED" in caplog.text
        # Service provider should not be called
        service_provider.get_required_service.assert_not_called()

    def test_registration_skipped_with_invalid_configuration(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that registration is skipped when configuration is invalid."""
        # Create a config with conflicting settings
        config = AppConfig(
            sandboxing=SandboxingConfiguration(
                enabled=True,
                strict_mode=True,  # Conflicting with enabled=False would be caught
                custom_tool_patterns=[],
                default_tool_patterns=[],  # This will cause validation error
            )
        )
        service_provider = Mock(spec=IServiceProvider)

        with caplog.at_level(logging.ERROR):
            _register_sandboxing_handler(config, service_provider)

        assert "configuration is invalid" in caplog.text
        assert "Sandboxing will be disabled" in caplog.text
        # Service provider should not be called
        service_provider.get_required_service.assert_not_called()

    def test_registration_skipped_when_project_resolution_disabled(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that registration is skipped when project directory resolution is disabled."""
        from src.core.config.app_config import SessionConfig

        config = AppConfig(
            sandboxing=SandboxingConfiguration(enabled=True),
            session=SessionConfig(project_dir_resolution_mode="disabled"),
        )

        service_provider = Mock(spec=IServiceProvider)

        with caplog.at_level(logging.INFO):
            _register_sandboxing_handler(config, service_provider)

        assert "project directory resolution is DISABLED" in caplog.text
        assert (
            "File access sandboxing status: DISABLED (dependency not met)"
            in caplog.text
        )
        # Service provider should not be called
        service_provider.get_required_service.assert_not_called()

    def test_successful_registration(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test successful registration status logging when sandboxing is enabled.

        Note: Sandboxing handler registration is now done via UnifiedToolSecurityHandler
        in the reactor factory. This function only logs the sandboxing status.
        """
        from src.core.config.app_config import SessionConfig

        config = AppConfig(
            sandboxing=SandboxingConfiguration(enabled=True),
            session=SessionConfig(project_dir_resolution_mode="auto"),
        )

        # Mock service provider - not used since we no longer register the handler here
        service_provider = Mock(spec=IServiceProvider)

        with caplog.at_level(logging.INFO):
            _register_sandboxing_handler(config, service_provider)

        # Verify the new log message about unified handler
        assert "File access sandboxing: ENABLED (via UnifiedToolSecurityHandler)" in caplog.text
        # Service provider should not be called since registration is done elsewhere
        service_provider.get_required_service.assert_not_called()

    def test_unified_handler_message_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that the unified handler message is logged when sandboxing is enabled.

        Note: Since sandboxing handler registration is now done via UnifiedToolSecurityHandler
        in the reactor factory, this function no longer calls service provider methods and
        cannot raise exceptions from service resolution. This test verifies that the
        unified handler message is logged correctly.
        """
        from src.core.config.app_config import SessionConfig

        config = AppConfig(
            sandboxing=SandboxingConfiguration(enabled=True),
            session=SessionConfig(project_dir_resolution_mode="auto"),
        )

        # Mock service provider - not used since function only logs now
        service_provider = Mock(spec=IServiceProvider)

        with caplog.at_level(logging.INFO):
            # Should not raise an exception and should log unified handler message
            _register_sandboxing_handler(config, service_provider)

        # Function now logs the unified handler message instead of registering
        assert "UnifiedToolSecurityHandler" in caplog.text


class TestConfigurationValidationAtStartup:
    """Test configuration validation scenarios at startup."""

    def test_invalid_regex_patterns_detected(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that invalid regex patterns are detected at startup."""
        # Note: This should be caught during config creation, but we test the validate_configuration method
        config = SandboxingConfiguration(enabled=True)
        # Manually set invalid default patterns to test validation
        config = SandboxingConfiguration(
            enabled=True,
            custom_tool_patterns=["valid_pattern"],
            default_tool_patterns=["[invalid("],  # Invalid regex
        )

        errors = config.validate_configuration()

        assert len(errors) > 0
        assert any("Invalid default tool pattern" in error for error in errors)

    def test_conflicting_settings_detected(self) -> None:
        """Test that conflicting settings are detected."""
        config = SandboxingConfiguration(enabled=False, strict_mode=True)

        errors = config.validate_configuration()

        assert len(errors) > 0
        assert any("strict_mode" in error and "disabled" in error for error in errors)

    def test_missing_tool_patterns_detected(self) -> None:
        """Test that missing tool patterns are detected when sandboxing is enabled."""
        config = SandboxingConfiguration(
            enabled=True,
            default_tool_patterns=[],
            custom_tool_patterns=[],
        )

        errors = config.validate_configuration()

        assert len(errors) > 0
        assert any("no tool patterns are defined" in error for error in errors)

    def test_valid_configuration_passes(self) -> None:
        """Test that a valid configuration passes validation."""
        config = SandboxingConfiguration(
            enabled=True,
            strict_mode=True,
            allow_parent_access=False,
            custom_tool_patterns=["custom_.*"],
        )

        errors = config.validate_configuration()

        assert len(errors) == 0
