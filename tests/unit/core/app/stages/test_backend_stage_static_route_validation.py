"""
Test cases for static_route validation in BackendStage.

This module tests the fail-fast validation that prevents the proxy from starting
with invalid backend names in the --static-route parameter.
"""

import pytest
from src.core.app.stages.backend import BackendStage
from src.core.config.app_config import AppConfig, BackendSettings


class TestBackendStageStaticRouteValidation:
    """Test static_route validation in BackendStage."""

    def setup_method(self):
        """Set up test fixtures."""
        self.stage = BackendStage()

        # Import connectors to register backends
        import importlib

        importlib.import_module("src.connectors")

    def test_valid_static_route_passes_validation(self):
        """Test that valid static_route backend passes validation."""
        backends = BackendSettings()
        backends.static_route = "gemini-oauth-plan:gemini-2.5-pro"
        config = AppConfig(backends=backends)

        # Should not raise any exception
        self.stage._validate_static_route_backend(config)

    def test_another_valid_static_route_passes_validation(self):
        """Test that another valid static_route backend passes validation."""
        backends = BackendSettings()
        backends.static_route = "openai:gpt-4"
        config = AppConfig(backends=backends)

        # Should not raise any exception
        self.stage._validate_static_route_backend(config)

    def test_no_static_route_passes_validation(self):
        """Test that config without static_route passes validation."""
        config = AppConfig()

        # Should not raise any exception
        self.stage._validate_static_route_backend(config)

    def test_empty_static_route_passes_validation(self):
        """Test that empty static_route passes validation."""
        backends = BackendSettings()
        backends.static_route = ""
        config = AppConfig(backends=backends)

        # Should not raise any exception
        self.stage._validate_static_route_backend(config)

    def test_none_static_route_passes_validation(self):
        """Test that None static_route passes validation."""
        backends = BackendSettings()
        backends.static_route = None
        config = AppConfig(backends=backends)

        # Should not raise any exception
        self.stage._validate_static_route_backend(config)

    def test_invalid_static_route_fails_validation(self):
        """Test that invalid static_route backend fails validation with descriptive error."""
        backends = BackendSettings()
        backends.static_route = (
            "gemini-cli-oauth-personal:gemini-2.5-pro"  # Old invalid name
        )
        config = AppConfig(backends=backends)

        with pytest.raises(ValueError) as exc_info:
            self.stage._validate_static_route_backend(config)

        error_msg = str(exc_info.value)

        # Verify error message contains all expected information
        assert "gemini-cli-oauth-personal" in error_msg
        assert "not registered" in error_msg
        assert "Available backends:" in error_msg
        assert "gemini-oauth-plan" in error_msg  # Should suggest correct backend
        assert "gemini-oauth-free" in error_msg  # Should suggest correct backend
        assert "Current static_route value:" in error_msg
        assert "Expected format:" in error_msg
        assert "Example:" in error_msg

    def test_completely_invalid_backend_fails_validation(self):
        """Test that completely invalid backend name fails validation."""
        backends = BackendSettings()
        backends.static_route = "nonexistent-backend:some-model"
        config = AppConfig(backends=backends)

        with pytest.raises(ValueError) as exc_info:
            self.stage._validate_static_route_backend(config)

        error_msg = str(exc_info.value)
        assert "nonexistent-backend" in error_msg
        assert "not registered" in error_msg
        assert "Available backends:" in error_msg

    def test_malformed_static_route_with_no_colon_fails_validation(self):
        """Test that malformed static_route without colon fails validation."""
        backends = BackendSettings()
        backends.static_route = "invalid-backend-name-only"
        config = AppConfig(backends=backends)

        with pytest.raises(ValueError) as exc_info:
            self.stage._validate_static_route_backend(config)

        error_msg = str(exc_info.value)
        assert "invalid-backend-name-only" in error_msg
        assert "not registered" in error_msg

    def test_error_message_format_and_content(self):
        """Test that error message has proper format and helpful content."""
        backends = BackendSettings()
        backends.static_route = "old-backend:model"
        config = AppConfig(backends=backends)

        with pytest.raises(ValueError) as exc_info:
            self.stage._validate_static_route_backend(config)

        error_msg = str(exc_info.value)
        lines = error_msg.split("\n")

        # Should be multi-line with specific structure
        assert len(lines) >= 6
        assert (
            "Invalid backend 'old-backend' specified in --static-route parameter."
            in lines[0]
        )
        assert "Backend 'old-backend' is not registered." in lines[1]
        assert lines[2].startswith("Available backends:")
        assert "Current static_route value: 'old-backend:model'" in lines[3]
        assert "Expected format: <backend_name>:<model_name>" in lines[4]
        assert lines[5].startswith("Example:")

    def test_available_backends_list_contains_expected_backends(self):
        """Test that available backends list contains expected registered backends."""
        backends = BackendSettings()
        backends.static_route = "invalid:model"
        config = AppConfig(backends=backends)

        with pytest.raises(ValueError) as exc_info:
            self.stage._validate_static_route_backend(config)

        error_msg = str(exc_info.value)

        # Should contain key backends that we know are registered
        expected_backends = [
            "openai",
            "anthropic",
            "gemini",
            "gemini-oauth-plan",
            "gemini-oauth-free",
            "openrouter",
        ]

        for backend in expected_backends:
            assert (
                backend in error_msg
            ), f"Expected backend '{backend}' not found in error message"
