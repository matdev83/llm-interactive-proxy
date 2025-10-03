"""Unit tests for BackendConfigProvider."""

import pytest

# Suppress Windows ProactorEventLoop warnings for this module
pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)

from src.core.config.app_config import AppConfig, BackendConfig
from src.core.interfaces.backend_config_provider_interface import IBackendConfigProvider
from src.core.services.backend_config_provider import BackendConfigProvider


class TestBackendConfigProvider:
    """Test suite for BackendConfigProvider."""

    def test_get_backend_config_with_attribute_access(self) -> None:
        """Test getting a backend config using attribute access."""
        # Arrange
        app_config = AppConfig()
        # Set directly in __dict__ to ensure it's properly set
        app_config.backends.__dict__["test_backend"] = BackendConfig(
            api_key=["test-key"]
        )
        provider = BackendConfigProvider(app_config)

        # Act
        config = provider.get_backend_config("test_backend")

        # Assert
        assert config is not None
        assert isinstance(config, BackendConfig)
        assert config.api_key == ["test-key"]

    def test_get_backend_config_with_dict_access(self) -> None:
        """Test getting a backend config using dictionary access."""
        # Arrange
        app_config = AppConfig()
        app_config.backends = {"openai": {"api_key": ["test-key"]}}  # type: ignore
        provider = BackendConfigProvider(app_config)

        # Act
        config = provider.get_backend_config("openai")

        # Assert
        assert config is not None
        assert isinstance(config, BackendConfig)
        assert config.api_key == ["test-key"]

    def test_get_backend_config_with_nonexistent_backend(self) -> None:
        """Test getting a config for a backend that doesn't exist."""
        # Arrange
        app_config = AppConfig()
        provider = BackendConfigProvider(app_config)

        # Act
        config = provider.get_backend_config("nonexistent")

        # Assert
        assert config is not None
        assert isinstance(config, BackendConfig)
        assert config.api_key == []

    def test_get_backend_config_with_empty_backend(self) -> None:
        """Test getting a config for a backend with empty config."""
        # Arrange
        app_config = AppConfig()
        app_config.backends.openai = BackendConfig()
        provider = BackendConfigProvider(app_config)

        # Act
        config = provider.get_backend_config("openai")

        # Assert
        assert config is not None
        assert isinstance(config, BackendConfig)
        assert config.api_key == []

    def test_iter_backend_names(self) -> None:
        """Test iterating over backend names."""
        # Arrange
        app_config = AppConfig()
        # Directly set in __dict__ to ensure it's visible
        app_config.backends.__dict__["test_backend1"] = BackendConfig(
            api_key=["test-key"]
        )
        app_config.backends.__dict__["test_backend2"] = BackendConfig(
            api_key=["test-key-2"]
        )
        provider = BackendConfigProvider(app_config)

        # Act
        backend_names = list(provider.iter_backend_names())

        # Assert
        assert "test_backend1" in backend_names
        assert "test_backend2" in backend_names

    def test_get_default_backend(self) -> None:
        """Test getting the default backend."""
        # Arrange
        app_config = AppConfig()
        app_config.backends.default_backend = "gemini"
        provider = BackendConfigProvider(app_config)

        # Act
        default_backend = provider.get_default_backend()

        # Assert
        assert default_backend == "gemini"

    def test_get_default_backend_fallback(self) -> None:
        """Test getting the default backend when not set."""
        # Arrange
        app_config = AppConfig()
        app_config.backends.default_backend = ""
        provider = BackendConfigProvider(app_config)

        # Act
        default_backend = provider.get_default_backend()

        # Assert
        assert default_backend == "openai"  # Default fallback

    def test_functional_backends(self) -> None:
        """Test getting functional backends."""
        # Arrange
        app_config = AppConfig()
        # Set directly in __dict__ to ensure it's properly set
        app_config.backends.__dict__["test_backend1"] = BackendConfig(
            api_key=["test-key"]
        )
        app_config.backends.__dict__["test_backend2"] = BackendConfig()  # No API key
        provider = BackendConfigProvider(app_config)

        # Act
        functional_backends = provider.get_functional_backends()

        # Assert
        assert "test_backend1" in functional_backends
        assert "test_backend2" not in functional_backends

    def test_implements_interface(self) -> None:
        """Test that BackendConfigProvider implements IBackendConfigProvider."""
        # Arrange
        app_config = AppConfig()
        provider = BackendConfigProvider(app_config)

        # Act/Assert
        assert isinstance(provider, IBackendConfigProvider)
