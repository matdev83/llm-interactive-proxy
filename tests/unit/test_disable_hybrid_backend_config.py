"""Tests for disable_hybrid_backend configuration."""

import os
from unittest.mock import patch

from src.core.config.app_config import AppConfig, BackendSettings


class TestDisableHybridBackendConfig:
    """Test suite for disable_hybrid_backend configuration."""

    def test_backend_settings_has_disable_hybrid_backend_field(self) -> None:
        """Test that BackendSettings has disable_hybrid_backend field with default False."""
        backend_settings = BackendSettings()
        assert hasattr(backend_settings, "disable_hybrid_backend")
        assert backend_settings.disable_hybrid_backend is False

    def test_app_config_has_disable_hybrid_backend_in_backends(self) -> None:
        """Test that AppConfig.backends has disable_hybrid_backend field."""
        config = AppConfig()
        assert hasattr(config.backends, "disable_hybrid_backend")
        assert config.backends.disable_hybrid_backend is False

    def test_disable_hybrid_backend_can_be_set_to_true(self) -> None:
        """Test that disable_hybrid_backend can be set to True."""
        backend_settings = BackendSettings(disable_hybrid_backend=True)
        assert backend_settings.disable_hybrid_backend is True

    def test_disable_hybrid_backend_from_environment_variable(self) -> None:
        """Test that DISABLE_HYBRID_BACKEND environment variable is read correctly."""
        with patch.dict(os.environ, {"DISABLE_HYBRID_BACKEND": "true"}):
            config = AppConfig.from_env()
            assert config.backends.disable_hybrid_backend is True

        with patch.dict(os.environ, {"DISABLE_HYBRID_BACKEND": "false"}):
            config = AppConfig.from_env()
            assert config.backends.disable_hybrid_backend is False

        with patch.dict(os.environ, {"DISABLE_HYBRID_BACKEND": "1"}):
            config = AppConfig.from_env()
            assert config.backends.disable_hybrid_backend is True

        with patch.dict(os.environ, {"DISABLE_HYBRID_BACKEND": "0"}):
            config = AppConfig.from_env()
            assert config.backends.disable_hybrid_backend is False

    def test_disable_hybrid_backend_default_when_env_not_set(self) -> None:
        """Test that disable_hybrid_backend defaults to False when env var not set."""
        # Ensure the env var is not set
        env_without_flag = {
            k: v for k, v in os.environ.items() if k != "DISABLE_HYBRID_BACKEND"
        }
        with patch.dict(os.environ, env_without_flag, clear=True):
            config = AppConfig.from_env()
            assert config.backends.disable_hybrid_backend is False

    def test_app_config_with_backends_override(self) -> None:
        """Test creating AppConfig with backends override including disable_hybrid_backend."""
        config = AppConfig(
            backends=BackendSettings(
                default_backend="openai",
                disable_hybrid_backend=True,
            )
        )
        assert config.backends.disable_hybrid_backend is True
        assert config.backends.default_backend == "openai"
