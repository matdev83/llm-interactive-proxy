"""
Unit tests for runtime static_route configuration validation.

This module tests the validate_static_route function that validates
the final resolved AppConfig.static_route value against registered backends.
"""

from __future__ import annotations

import importlib

import pytest
from src.core.common.exceptions import ConfigurationError
from src.core.config.app_config import AppConfig, BackendSettings
from src.core.config.semantic_validation import validate_static_route


class TestValidateStaticRoute:
    """Test suite for validate_static_route function."""

    @pytest.fixture(autouse=True)
    def setup_connectors(self):
        """Import connectors to populate backend registry before each test."""
        # Import connectors package to trigger auto-discovery and registration
        importlib.import_module("src.connectors")
        yield
        # No cleanup needed - registry state persists but doesn't affect test isolation

    def test_valid_static_route_gemini_passes(self):
        """Test that valid static_route with gemini backend passes validation."""
        backends = BackendSettings()
        backends.static_route = "gemini-oauth-plan:gemini-2.5-pro"
        config = AppConfig(backends=backends)

        # Should not raise any exception
        validate_static_route(config)

    def test_valid_static_route_openai_passes(self):
        """Test that valid static_route with openai backend passes validation."""
        backends = BackendSettings()
        backends.static_route = "openai:gpt-4"
        config = AppConfig(backends=backends)

        # Should not raise any exception
        validate_static_route(config)

    def test_valid_static_route_anthropic_passes(self):
        """Test that valid static_route with anthropic backend passes validation."""
        backends = BackendSettings()
        backends.static_route = "anthropic:claude-3-opus"
        config = AppConfig(backends=backends)

        # Should not raise any exception
        validate_static_route(config)

    def test_valid_static_route_openrouter_passes(self):
        """Test that valid static_route with openrouter backend passes validation."""
        backends = BackendSettings()
        backends.static_route = "openrouter:anthropic/claude-3-opus"
        config = AppConfig(backends=backends)

        # Should not raise any exception
        validate_static_route(config)

    def test_none_static_route_passes(self):
        """Test that None static_route passes validation (no-op)."""
        backends = BackendSettings()
        backends.static_route = None
        config = AppConfig(backends=backends)

        # Should not raise any exception
        validate_static_route(config)

    def test_empty_string_static_route_passes(self):
        """Test that empty string static_route passes validation (no-op)."""
        backends = BackendSettings()
        backends.static_route = ""
        config = AppConfig(backends=backends)

        # Should not raise any exception
        validate_static_route(config)

    def test_invalid_backend_name_raises_configuration_error(self):
        """Test that invalid backend name raises ConfigurationError with actionable details."""
        backends = BackendSettings()
        backends.static_route = "nonexistent-backend:some-model"
        config = AppConfig(backends=backends)

        with pytest.raises(ConfigurationError) as exc_info:
            validate_static_route(config)

        exc = exc_info.value
        # Assert error message contains the current static_route value
        assert "nonexistent-backend:some-model" in exc.message
        assert "nonexistent-backend" in exc.message

        # Assert error details are actionable
        assert "details" in exc.details or exc.details
        assert exc.details.get("invalid_backend") == "nonexistent-backend"
        assert exc.details.get("static_route") == "nonexistent-backend:some-model"
        assert "expected_format" in exc.details
        assert exc.details["expected_format"] == "<backend_name>:<model_name>"
        assert "example" in exc.details
        assert exc.details["example"] == "gemini-oauth-plan:gemini-2.5-pro"

        # Assert available_backends list contains known backends
        assert "available_backends" in exc.details
        available_backends = exc.details["available_backends"]
        assert isinstance(available_backends, list)
        assert len(available_backends) > 0

        # Verify known backends are in the list
        known_backends = ["openai", "anthropic", "gemini-oauth-plan", "openrouter"]
        for backend in known_backends:
            assert (
                backend in available_backends
            ), f"Expected backend '{backend}' not found in available_backends list"

    def test_missing_delimiter_raises_configuration_error(self):
        """Test that missing colon delimiter raises ConfigurationError."""
        backends = BackendSettings()
        backends.static_route = "openai-gpt-4"  # Missing colon
        config = AppConfig(backends=backends)

        with pytest.raises(ConfigurationError) as exc_info:
            validate_static_route(config)

        exc = exc_info.value
        # Assert error message contains the current static_route value
        assert "openai-gpt-4" in exc.message

        # Assert error details are actionable
        assert exc.details.get("static_route") == "openai-gpt-4"
        assert "expected_format" in exc.details
        assert exc.details["expected_format"] == "<backend_name>:<model_name>"
        assert "example" in exc.details
        assert exc.details["example"] == "gemini-oauth-plan:gemini-2.5-pro"

    def test_empty_model_part_raises_configuration_error(self):
        """Test that empty model part (e.g., 'openai:') raises ConfigurationError."""
        backends = BackendSettings()
        backends.static_route = "openai:"  # Empty model part
        config = AppConfig(backends=backends)

        with pytest.raises(ConfigurationError) as exc_info:
            validate_static_route(config)

        exc = exc_info.value
        # Assert error message contains the current static_route value
        assert "openai:" in exc.message
        assert (
            "Model name cannot be empty" in exc.message
            or "empty" in exc.message.lower()
        )

        # Assert error details are actionable
        assert exc.details.get("static_route") == "openai:"
        assert "expected_format" in exc.details
        assert exc.details["expected_format"] == "<backend_name>:<model_name>"
        assert "example" in exc.details
        assert exc.details["example"] == "gemini-oauth-plan:gemini-2.5-pro"

    def test_whitespace_only_model_part_raises_configuration_error(self):
        """Test that whitespace-only model part raises ConfigurationError."""
        backends = BackendSettings()
        backends.static_route = "openai:   "  # Whitespace-only model part
        config = AppConfig(backends=backends)

        with pytest.raises(ConfigurationError) as exc_info:
            validate_static_route(config)

        exc = exc_info.value
        # Assert error message contains the current static_route value
        assert "openai:" in exc.message or "openai:   " in exc.message

        # Assert error details are actionable
        assert exc.details.get("static_route") == "openai:   "
        assert "expected_format" in exc.details
        assert "example" in exc.details

    def test_error_message_contains_static_route_value(self):
        """Test that error message always contains the current static_route value."""
        test_cases = [
            ("invalid-backend:model", "invalid-backend:model"),
            ("no-colon", "no-colon"),
            ("backend:", "backend:"),
        ]

        for static_route_value, expected_in_message in test_cases:
            backends = BackendSettings()
            backends.static_route = static_route_value
            config = AppConfig(backends=backends)

            with pytest.raises(ConfigurationError) as exc_info:
                validate_static_route(config)

            exc = exc_info.value
            assert expected_in_message in exc.message, (
                f"Error message should contain '{expected_in_message}' "
                f"for static_route '{static_route_value}'"
            )

    def test_available_backends_list_is_sorted(self):
        """Test that available_backends list in error details is sorted."""
        backends = BackendSettings()
        backends.static_route = "invalid-backend:model"
        config = AppConfig(backends=backends)

        with pytest.raises(ConfigurationError) as exc_info:
            validate_static_route(config)

        exc = exc_info.value
        available_backends = exc.details.get("available_backends", [])
        assert available_backends == sorted(
            available_backends
        ), "available_backends should be sorted"
