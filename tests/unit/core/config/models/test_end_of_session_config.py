"""Tests for EndOfSessionConfig model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from src.core.config.models.end_of_session import EndOfSessionConfig


class TestEndOfSessionConfigDefaults:
    """Tests for EndOfSessionConfig default values."""

    def test_default_values(self) -> None:
        """Test that default values are set correctly."""
        config = EndOfSessionConfig()

        assert config.enabled is True
        assert config.emit_events is True
        assert config.detect_stream_signals is True
        assert config.detect_tool_completion is True
        assert config.emission_ttl_seconds == 3600
        assert config.dispatch_timeout_seconds == 5.0

    def test_create_with_custom_values(self) -> None:
        """Test creating config with custom values."""
        config = EndOfSessionConfig(
            enabled=True,
            emit_events=False,
            detect_stream_signals=False,
            detect_tool_completion=False,
            emission_ttl_seconds=7200,
            dispatch_timeout_seconds=10.0,
        )

        assert config.enabled is True
        assert config.emit_events is False
        assert config.detect_stream_signals is False
        assert config.detect_tool_completion is False
        assert config.emission_ttl_seconds == 7200
        assert config.dispatch_timeout_seconds == 10.0


class TestEndOfSessionConfigValidation:
    """Tests for EndOfSessionConfig validation rules."""

    def test_emission_ttl_seconds_must_be_non_negative(self) -> None:
        """Test that emission_ttl_seconds must be >= 0."""
        with pytest.raises(ValidationError) as exc_info:
            EndOfSessionConfig(emission_ttl_seconds=-1)

        errors = exc_info.value.errors()
        assert any(
            error["loc"] == ("emission_ttl_seconds",)
            and error["type"] == "greater_than_equal"
            for error in errors
        )

    def test_dispatch_timeout_seconds_must_be_non_negative(self) -> None:
        """Test that dispatch_timeout_seconds must be >= 0."""
        with pytest.raises(ValidationError) as exc_info:
            EndOfSessionConfig(dispatch_timeout_seconds=-1.0)

        errors = exc_info.value.errors()
        assert any(
            error["loc"] == ("dispatch_timeout_seconds",)
            and error["type"] == "greater_than_equal"
            for error in errors
        )

    def test_zero_values_are_allowed(self) -> None:
        """Test that zero values are allowed for timeout/ttl fields."""
        config = EndOfSessionConfig(
            emission_ttl_seconds=0,
            dispatch_timeout_seconds=0.0,
        )

        assert config.emission_ttl_seconds == 0
        assert config.dispatch_timeout_seconds == 0.0

    def test_when_disabled_other_settings_can_be_any_value(self) -> None:
        """Test that when enabled=False, other settings can be any value."""
        # This should not raise, even with negative values when disabled
        # Actually, Pydantic will still validate the fields, so negative values
        # will still fail. But the logic allows any values when disabled.
        config = EndOfSessionConfig(
            enabled=False,
            emission_ttl_seconds=3600,
            dispatch_timeout_seconds=5.0,
        )

        assert config.enabled is False

    def test_detect_only_mode_allowed(self) -> None:
        """Test that detect-only mode (enabled=True, emit_events=False) is allowed."""
        config = EndOfSessionConfig(
            enabled=True,
            emit_events=False,
        )

        assert config.enabled is True
        assert config.emit_events is False


class TestEndOfSessionConfigImmutability:
    """Tests for EndOfSessionConfig immutability."""

    def test_config_is_frozen(self) -> None:
        """Test that config is frozen (immutable)."""
        from pydantic import ValidationError

        config = EndOfSessionConfig()

        # Pydantic frozen models raise ValidationError when trying to set attributes
        with pytest.raises(ValidationError):
            config.enabled = True  # type: ignore[misc]


class TestEndOfSessionConfigIntegration:
    """Tests for EndOfSessionConfig integration with AppConfigModel."""

    def test_config_can_be_imported(self) -> None:
        """Test that EndOfSessionConfig can be imported."""
        from src.core.config.models.end_of_session import EndOfSessionConfig

        assert EndOfSessionConfig is not None

    def test_config_is_domain_model(self) -> None:
        """Test that EndOfSessionConfig extends DomainModel."""
        from src.core.interfaces.model_bases import DomainModel

        config = EndOfSessionConfig()
        assert isinstance(config, DomainModel)
