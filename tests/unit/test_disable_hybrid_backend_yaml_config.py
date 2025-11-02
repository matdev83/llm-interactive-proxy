"""Tests for disable_hybrid_backend YAML configuration file support."""

import tempfile
from pathlib import Path

import yaml
from src.core.config.app_config import load_config


class TestDisableHybridBackendYAMLConfig:
    """Test suite for YAML configuration file support of disable_hybrid_backend."""

    def test_yaml_config_with_disable_hybrid_backend_true(self) -> None:
        """Test loading config from YAML file with disable_hybrid_backend: true."""
        # Create temporary YAML config file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            config_data = {
                "backends": {
                    "default_backend": "openai",
                    "disable_hybrid_backend": True,
                }
            }
            yaml.dump(config_data, f)
            config_path = f.name

        try:
            # Load config from file, ensuring no env var interference
            config = load_config(config_path, environ={})

            # Verify
            assert config.backends.disable_hybrid_backend is True
            assert config.backends.default_backend == "openai"
        finally:
            # Cleanup
            Path(config_path).unlink(missing_ok=True)

    def test_yaml_config_with_disable_hybrid_backend_false(self) -> None:
        """Test loading config from YAML file with disable_hybrid_backend: false."""
        # Create temporary YAML config file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            config_data = {
                "backends": {
                    "default_backend": "openai",
                    "disable_hybrid_backend": False,
                }
            }
            yaml.dump(config_data, f)
            config_path = f.name

        try:
            # Load config from file, ensuring no env var interference
            config = load_config(config_path, environ={})

            # Verify
            assert config.backends.disable_hybrid_backend is False
            assert config.backends.default_backend == "openai"
        finally:
            # Cleanup
            Path(config_path).unlink(missing_ok=True)

    def test_yaml_config_without_disable_hybrid_backend_defaults_to_false(self) -> None:
        """Test that disable_hybrid_backend defaults to False when not in YAML config."""
        # Create temporary YAML config file without disable_hybrid_backend
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            config_data = {
                "backends": {
                    "default_backend": "openai",
                }
            }
            yaml.dump(config_data, f)
            config_path = f.name

        try:
            # Load config from file, ensuring no env var interference
            config = load_config(config_path, environ={})

            # Verify default is False
            assert config.backends.disable_hybrid_backend is False
        finally:
            # Cleanup
            Path(config_path).unlink(missing_ok=True)

    def test_yaml_config_with_multiple_backend_settings(self) -> None:
        """Test YAML config with disable_hybrid_backend alongside other backend settings."""
        # Create temporary YAML config file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            config_data = {
                "backends": {
                    "default_backend": "anthropic",
                    "disable_hybrid_backend": True,
                    "disable_gemini_oauth_fallback": True,
                }
            }
            yaml.dump(config_data, f)
            config_path = f.name

        try:
            # Load config from file, ensuring no env var interference
            config = load_config(config_path, environ={})

            # Verify all settings are loaded
            assert config.backends.disable_hybrid_backend is True
            assert config.backends.disable_gemini_oauth_fallback is True
            assert config.backends.default_backend == "anthropic"
        finally:
            # Cleanup
            Path(config_path).unlink(missing_ok=True)
