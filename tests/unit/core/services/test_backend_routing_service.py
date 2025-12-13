from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from src.core.common.exceptions import RoutingError
from src.core.config.app_config import BackendConfig, RoutingConfig
from src.core.services.backend_routing_service import BackendRoutingService


@pytest.fixture
def mock_config_provider():
    provider = Mock()
    provider.configs = {
        "openai.1": BackendConfig(api_key="k1", models=["gpt-4"]),
        "openai.2": BackendConfig(api_key="k2", models=["gpt-4", "gpt-3.5"]),
        "anthropic.1": BackendConfig(api_key="k3", models=["claude-3"]),
    }

    def get_config(name):
        return provider.configs.get(name)

    def iter_names():
        return provider.configs.keys()

    provider.get_backend_config.side_effect = get_config
    provider.iter_backend_names.side_effect = iter_names
    return provider


class TestBackendRoutingService:

    def test_explicit_routing_success(self, mock_config_provider):
        service = BackendRoutingService(mock_config_provider, RoutingConfig())
        result = service.resolve_backend_instance("openai.1", "gpt-4")
        assert result == "openai.1"

    def test_generic_routing_round_robin(self, mock_config_provider):
        service = BackendRoutingService(mock_config_provider, RoutingConfig())

        # Should alternate between openai.1 and openai.2
        results = set()
        for _ in range(10):
            res = service.resolve_backend_instance("openai", "gpt-4")
            results.add(res)

        assert "openai.1" in results
        assert "openai.2" in results
        assert len(results) == 2

    def test_model_routing_discovery(self, mock_config_provider):
        service = BackendRoutingService(mock_config_provider, RoutingConfig())

        # gpt-4 is on openai.1 and openai.2
        results_gpt4 = set()
        for _ in range(10):
            res = service.resolve_backend_instance(None, "gpt-4")
            results_gpt4.add(res)
        assert "openai.1" in results_gpt4
        assert "openai.2" in results_gpt4

        # vendor/model should match plain model entries too
        results_vendor_gpt4 = set()
        for _ in range(10):
            res = service.resolve_backend_instance(None, "openai/gpt-4")
            results_vendor_gpt4.add(res)
        assert "openai.1" in results_vendor_gpt4
        assert "openai.2" in results_vendor_gpt4

        # claude-3 is only on anthropic.1
        res_claude = service.resolve_backend_instance(None, "claude-3")
        assert res_claude == "anthropic.1"

        res_vendor_claude = service.resolve_backend_instance(None, "anthropic/claude-3")
        assert res_vendor_claude == "anthropic.1"

    def test_policy_disable_backend_ids(self, mock_config_provider):
        config = RoutingConfig(disable_backend_ids=True)
        service = BackendRoutingService(mock_config_provider, config)

        # Explicit ID should fail
        with pytest.raises(RoutingError) as exc:
            service.resolve_backend_instance("openai.1", "gpt-4")
        assert "explicit backend instance ID" in str(exc.value)

        # Generic name should succeed
        assert service.resolve_backend_instance("openai", "gpt-4") in [
            "openai.1",
            "openai.2",
        ]

        # Model name should succeed
        assert service.resolve_backend_instance(None, "gpt-4") in [
            "openai.1",
            "openai.2",
        ]

    def test_policy_disable_backend_names(self, mock_config_provider):
        config = RoutingConfig(disable_backend_names=True)
        service = BackendRoutingService(mock_config_provider, config)

        # Explicit ID should fail (implied)
        with pytest.raises(RoutingError) as exc:
            service.resolve_backend_instance("openai.1", "gpt-4")
        assert "explicit backend instance ID" in str(exc.value)

        # Generic name should fail
        with pytest.raises(RoutingError) as exc:
            service.resolve_backend_instance("openai", "gpt-4")
        assert "backend name" in str(exc.value)

        # Model name should succeed
        assert service.resolve_backend_instance(None, "gpt-4") in [
            "openai.1",
            "openai.2",
        ]

    def test_policy_disable_model_names(self, mock_config_provider):
        config = RoutingConfig(disable_model_names=True)
        service = BackendRoutingService(mock_config_provider, config)

        # Explicit ID should succeed
        assert service.resolve_backend_instance("openai.1", "gpt-4") == "openai.1"

        # Generic name should succeed
        assert service.resolve_backend_instance("openai", "gpt-4") in [
            "openai.1",
            "openai.2",
        ]

        # Model name should fail
        with pytest.raises(RoutingError) as exc:
            service.resolve_backend_instance(None, "gpt-4")
        assert "model name only" in str(exc.value)

    def test_generic_routing_fallback_if_no_instances(self, mock_config_provider):
        # Scenario where "custom" backend exists in config but has no "custom.1" instances
        # The service should return "custom" as is (legacy behavior compatibility)
        service = BackendRoutingService(mock_config_provider, RoutingConfig())

        # Mock provider returns no instances for "custom"
        # But resolve_generic_backend should fall back to the name itself if no instances found
        res = service.resolve_backend_instance("custom", "model")
        assert res == "custom"

    def test_excluded_backends_are_skipped(self, mock_config_provider):
        service = BackendRoutingService(mock_config_provider, RoutingConfig())

        # Exclude openai.1 and ensure round-robin sticks to openai.2
        excluded = {"openai.1"}
        for _ in range(3):
            res = service.resolve_backend_instance(
                "openai", "gpt-4", excluded_backends=excluded
            )
            assert res == "openai.2"

        # Exclude the only provider for claude-3 -> returns None
        res = service.resolve_backend_instance(
            None, "claude-3", excluded_backends={"anthropic.1"}
        )
        assert res is None


class TestRoutingConfigValidation:
    """Tests for RoutingConfig validation rules."""

    def test_valid_config_all_enabled(self):
        """Default config with all methods enabled should be valid."""
        config = RoutingConfig()
        assert config.disable_backend_ids is False
        assert config.disable_backend_names is False
        assert config.disable_model_names is False

    def test_valid_config_disable_backend_ids_only(self):
        """Disabling only backend IDs is valid."""
        config = RoutingConfig(disable_backend_ids=True)
        assert config.disable_backend_ids is True

    def test_valid_config_disable_backend_names_only(self):
        """Disabling backend names (implies IDs) is valid if model names enabled."""
        config = RoutingConfig(disable_backend_names=True)
        assert config.disable_backend_names is True

    def test_valid_config_disable_model_names_only(self):
        """Disabling model names is valid if backend names enabled."""
        config = RoutingConfig(disable_model_names=True)
        assert config.disable_model_names is True

    def test_valid_config_disable_ids_and_model_names(self):
        """Disabling IDs and model names is valid (backend names still work)."""
        config = RoutingConfig(disable_backend_ids=True, disable_model_names=True)
        assert config.disable_backend_ids is True
        assert config.disable_model_names is True

    def test_invalid_config_disable_backend_names_and_model_names(self):
        """Disabling both backend names and model names is invalid."""
        with pytest.raises(ValidationError) as exc:
            RoutingConfig(disable_backend_names=True, disable_model_names=True)
        assert "cannot disable both backend names and model-only routing" in str(
            exc.value
        )

    def test_invalid_config_all_disabled(self):
        """Disabling all routing methods is invalid."""
        with pytest.raises(ValidationError) as exc:
            RoutingConfig(
                disable_backend_ids=True,
                disable_backend_names=True,
                disable_model_names=True,
            )
        assert "cannot disable both backend names and model-only routing" in str(
            exc.value
        )
