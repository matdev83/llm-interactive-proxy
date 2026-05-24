"""Tests for health check configuration models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from src.core.domain.configuration.health_check_config import (
    HealthCheckConfig,
    HttpCheckConfig,
    PingCheckConfig,
)


class TestPingCheckConfig:
    """Tests for PingCheckConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = PingCheckConfig()

        assert config.enabled is True
        assert config.interval_seconds == 30
        assert config.timeout_seconds == 5
        assert config.failure_threshold == 3
        assert config.count == 1

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = PingCheckConfig(
            enabled=False,
            interval_seconds=60,
            timeout_seconds=10,
            failure_threshold=5,
            count=3,
        )

        assert config.enabled is False
        assert config.interval_seconds == 60
        assert config.timeout_seconds == 10
        assert config.failure_threshold == 5
        assert config.count == 3

    def test_validation_interval_minimum(self) -> None:
        """Test that interval has minimum value."""
        with pytest.raises(ValidationError):
            PingCheckConfig(interval_seconds=4)  # Minimum is 5

    def test_validation_timeout_minimum(self) -> None:
        """Test that timeout has minimum value."""
        with pytest.raises(ValidationError):
            PingCheckConfig(timeout_seconds=0)  # Minimum is 1

    def test_frozen(self) -> None:
        """Test that config is immutable."""
        config = PingCheckConfig()
        with pytest.raises(ValidationError):
            config.enabled = False  # type: ignore[misc]


class TestHttpCheckConfig:
    """Tests for HttpCheckConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = HttpCheckConfig()

        assert config.enabled is True
        assert config.interval_seconds == 60
        assert config.timeout_seconds == 10
        assert config.failure_threshold == 2
        assert config.method == "HEAD"
        assert config.path == ""
        assert config.accept_any_response is True

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = HttpCheckConfig(
            enabled=False,
            interval_seconds=120,
            timeout_seconds=30,
            failure_threshold=5,
            method="GET",
            path="/health",
            accept_any_response=False,
        )

        assert config.enabled is False
        assert config.interval_seconds == 120
        assert config.timeout_seconds == 30
        assert config.failure_threshold == 5
        assert config.method == "GET"
        assert config.path == "/health"
        assert config.accept_any_response is False

    def test_validation_method(self) -> None:
        """Test that method must be GET or HEAD."""
        with pytest.raises(ValidationError):
            HttpCheckConfig(method="POST")


class TestHealthCheckConfig:
    """Tests for HealthCheckConfig."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = HealthCheckConfig()

        assert config.enabled is True
        assert config.log_healthy_checks is False
        assert isinstance(config.ping, PingCheckConfig)
        assert isinstance(config.http, HttpCheckConfig)

    def test_nested_config(self) -> None:
        """Test nested configuration."""
        config = HealthCheckConfig(
            enabled=True,
            ping=PingCheckConfig(interval_seconds=60),
            http=HttpCheckConfig(timeout_seconds=30),
        )

        assert config.ping.interval_seconds == 60
        assert config.http.timeout_seconds == 30

    def test_disabled(self) -> None:
        """Test disabled configuration."""
        config = HealthCheckConfig(enabled=False)
        assert config.enabled is False

    def test_from_dict(self) -> None:
        """Test creating config from dict."""
        data = {
            "enabled": True,
            "ping": {
                "enabled": True,
                "interval_seconds": 45,
            },
            "http": {
                "enabled": False,
            },
        }
        config = HealthCheckConfig.model_validate(data)

        assert config.enabled is True
        assert config.ping.interval_seconds == 45
        assert config.http.enabled is False
