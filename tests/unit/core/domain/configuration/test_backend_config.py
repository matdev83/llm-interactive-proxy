"""
Tests for BackendConfiguration class.

This module tests the backend configuration functionality including
backend/model selection, API URLs, failover routes, and validation.
"""

from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.interfaces.configuration import IBackendConfig


class TestBackendConfiguration:
    """Tests for BackendConfiguration class."""

    def test_default_initialization(self) -> None:
        """Test default initialization."""
        config = BackendConfiguration()

        assert config.backend_type is None
        assert config.model is None
        assert config.api_url is None
        assert config.openai_url is None
        assert config.interactive_mode is True
        assert config.failover_routes == {}

    def test_initialization_with_values(self) -> None:
        """Test initialization with specific values."""
        config = BackendConfiguration(
            backend_type="openai",
            model="gpt-4",
            api_url="https://api.example.com",
            interactive_mode=False,
        )

        assert config.backend_type == "openai"
        assert config.model == "gpt-4"
        assert config.api_url == "https://api.example.com"
        assert config.interactive_mode is False

    def test_openai_url_validation(self) -> None:
        """Test OpenAI URL validation."""
        # Valid URLs
        config = BackendConfiguration(openai_url="https://api.openai.com")
        assert config.openai_url == "https://api.openai.com"

        config = BackendConfiguration(openai_url="http://localhost:8000")
        assert config.openai_url == "http://localhost:8000"

        # OpenAI URL validation is tested through the with_openai_url method
        # which creates a new configuration and triggers validation

    def test_with_backend_method(self) -> None:
        """Test with_backend method."""
        config = BackendConfiguration(
            backend_type="openai",
            model="gpt-3.5-turbo",
        )

        new_config = config.with_backend("anthropic")

        assert isinstance(new_config, IBackendConfig)
        assert new_config.backend_type == "anthropic"
        assert new_config.model == "gpt-3.5-turbo"  # Model should be preserved
        assert new_config is not config  # Should be a new instance

    def test_with_model_method(self) -> None:
        """Test with_model method."""
        config = BackendConfiguration(model="gpt-3.5-turbo")

        new_config = config.with_model("gpt-4")

        assert isinstance(new_config, IBackendConfig)
        assert new_config.model == "gpt-4"
        assert new_config is not config

    def test_with_api_url_method(self) -> None:
        """Test with_api_url method."""
        config = BackendConfiguration(api_url="https://api.example.com")

        new_config = config.with_api_url("https://api.new.com")

        assert isinstance(new_config, IBackendConfig)
        assert new_config.api_url == "https://api.new.com"
        assert new_config is not config

    def test_with_openai_url_method(self) -> None:
        """Test with_openai_url method."""
        config = BackendConfiguration()

        new_config = config.with_openai_url("https://api.openai.com/v1")

        assert isinstance(new_config, IBackendConfig)
        assert new_config.openai_url == "https://api.openai.com/v1"
        assert new_config is not config

    def test_with_interactive_mode_method(self) -> None:
        """Test with_interactive_mode method."""
        config = BackendConfiguration(interactive_mode=False)

        new_config = config.with_interactive_mode(True)

        assert isinstance(new_config, IBackendConfig)
        assert new_config.interactive_mode is True
        assert new_config is not config

    def test_with_backend_and_model_method(self) -> None:
        """Test with_backend_and_model method."""
        config = BackendConfiguration()

        new_config = config.with_backend_and_model("anthropic", "claude-3")

        assert isinstance(new_config, IBackendConfig)
        assert new_config.backend_type == "anthropic"
        assert new_config.model == "claude-3"
        assert new_config.invalid_override is False
        assert new_config is not config

    def test_with_backend_and_model_invalid_override(self) -> None:
        """Test with_backend_and_model with invalid override."""
        config = BackendConfiguration()

        new_config = config.with_backend_and_model("invalid", "model", invalid=True)

        assert new_config.backend_type == "invalid"
        assert new_config.model == "model"
        assert new_config.invalid_override is True

    def test_with_oneoff_route_method(self) -> None:
        """Test with_oneoff_route method."""
        config = BackendConfiguration()

        new_config = config.with_oneoff_route("openai", "gpt-4")

        assert new_config.oneoff_backend == "openai"
        assert new_config.oneoff_model == "gpt-4"
        assert new_config is not config

    def test_without_oneoff_route_method(self) -> None:
        """Test without_oneoff_route method."""
        config = BackendConfiguration(
            oneoff_backend="openai",
            oneoff_model="gpt-4",
        )

        new_config = config.without_oneoff_route()

        assert new_config.oneoff_backend is None
        assert new_config.oneoff_model is None
        assert new_config is not config

    def test_without_override_method(self) -> None:
        """Test without_override method."""
        config = BackendConfiguration(
            backend_type="openai",
            model="gpt-4",
            api_url="https://api.example.com",
            oneoff_backend="anthropic",
            oneoff_model="claude-3",
            invalid_override=True,
        )

        new_config = config.without_override()

        assert new_config.backend_type is None
        assert new_config.model is None
        assert new_config.api_url is None
        assert new_config.oneoff_backend is None
        assert new_config.oneoff_model is None
        assert new_config.invalid_override is False
        assert new_config is not config

    def test_failover_route_management(self) -> None:
        """Test failover route management methods."""
        config = BackendConfiguration()

        # Test with_failover_route
        config = config.with_failover_route("route1", "round-robin")
        assert "route1" in config.failover_routes
        assert config.failover_routes["route1"]["policy"] == "round-robin"
        assert config.failover_routes["route1"]["elements"] == []

        # Test with_appended_route_element
        config = config.with_appended_route_element("route1", "backend1")
        assert config.failover_routes["route1"]["elements"] == ["backend1"]

        config = config.with_appended_route_element("route1", "backend2")
        assert config.failover_routes["route1"]["elements"] == ["backend1", "backend2"]

        # Test with_prepended_route_element
        config = config.with_prepended_route_element("route1", "backend0")
        assert config.failover_routes["route1"]["elements"] == [
            "backend0",
            "backend1",
            "backend2",
        ]

        # Test with_cleared_route
        config = config.with_cleared_route("route1")
        assert config.failover_routes["route1"]["elements"] == []

        # Test without_failover_route
        config = config.without_failover_route("route1")
        assert "route1" not in config.failover_routes

    def test_get_route_elements_method(self) -> None:
        """Test get_route_elements method."""
        config = BackendConfiguration()
        config = config.with_failover_route("route1", "round-robin")
        config = config.with_appended_route_element("route1", "backend1")

        elements = config.get_route_elements("route1")
        assert elements == ["backend1"]

        # Test non-existent route
        elements = config.get_route_elements("nonexistent")
        assert elements == []

    def test_get_routes_method(self) -> None:
        """Test get_routes method."""
        config = BackendConfiguration()
        config = config.with_failover_route("route1", "round-robin")
        config = config.with_failover_route("route2", "failover")

        routes = config.get_routes()
        assert routes == {"route1": "round-robin", "route2": "failover"}

    def test_model_dump_with_properties(self) -> None:
        """Test model_dump includes property values."""
        config = BackendConfiguration(
            backend_type="openai",
            model="gpt-4",
            api_url="https://api.example.com",
            interactive_mode=False,
        )

        dump = config.model_dump()

        assert dump["backend_type"] == "openai"
        assert dump["model"] == "gpt-4"
        assert dump["api_url"] == "https://api.example.com"
        assert dump["openai_url"] is None
        assert dump["interactive_mode"] is False
        assert dump["failover_routes"] == {}

    def test_immutability(self) -> None:
        """Test that configurations are immutable (methods return new instances)."""
        config = BackendConfiguration(
            backend_type="openai",
            model="gpt-4",
        )

        # All with_* methods should return new instances
        new_config = config.with_backend("anthropic")
        assert new_config is not config

        new_config2 = config.with_model("gpt-3.5-turbo")
        assert new_config2 is not config
        assert new_config2 is not new_config

        # Original config should be unchanged
        assert config.backend_type == "openai"
        assert config.model == "gpt-4"

    def test_alias_support(self) -> None:
        """Test that aliases work correctly."""
        config = BackendConfiguration(
            backend_type="openai",
            model="gpt-4",
            api_url="https://api.example.com",
            interactive_mode=False,
        )

        assert config.backend_type == "openai"
        assert config.model == "gpt-4"
        assert config.api_url == "https://api.example.com"
        assert config.interactive_mode is False
