import pytest
from pydantic import ValidationError
from src.core.config.models.auxiliary_routing import AuxiliaryRoutingConfig


class TestAuxiliaryRoutingConfig:
    def test_disabled_by_default(self):
        config = AuxiliaryRoutingConfig()
        assert config.enabled is False

    def test_valid_backend_config(self):
        """Backend explicitly provided."""
        config = AuxiliaryRoutingConfig(enabled=True, backend="openrouter")
        assert config.enabled is True
        assert config.backend == "openrouter"

    def test_valid_fqn_model_config(self):
        """Model with FQN provided, backend is None."""
        config = AuxiliaryRoutingConfig(enabled=True, model="openrouter:gemini-flash")
        assert config.enabled is True
        assert config.backend is None
        assert config.model == "openrouter:gemini-flash"

    def test_valid_both_config(self):
        """Both provided."""
        config = AuxiliaryRoutingConfig(
            enabled=True, backend="openrouter", model="gemini-flash"
        )
        assert config.enabled is True

    def test_invalid_missing_target(self):
        """Enabled but no backend and no FQN model."""
        with pytest.raises(ValidationError) as exc:
            AuxiliaryRoutingConfig(
                enabled=True, model="gemini-flash"  # No backend part
            )
        assert "target is configured" in str(exc.value)

    def test_invalid_missing_all(self):
        """Enabled but nothing else."""
        with pytest.raises(ValidationError) as exc:
            AuxiliaryRoutingConfig(enabled=True)
        assert "target is configured" in str(exc.value)

    def test_invalid_model_only_selector_with_colon_suffix(self):
        """Enabled model-only selector with ':' suffix must not be treated as backend:model."""
        with pytest.raises(ValidationError) as exc:
            AuxiliaryRoutingConfig(
                enabled=True,
                model="openrouter/anthropic/claude-3-haiku:free",
            )
        assert "backend:model" in str(exc.value)

    def test_default_patterns_include_new_ones(self):
        config = AuxiliaryRoutingConfig()
        patterns = config.detection_patterns
        assert any("session" in p for p in patterns)
        assert any("task" in p for p in patterns)

    def test_disable_default_openrouter_default(self):
        """disable_default_openrouter should default to False."""
        config = AuxiliaryRoutingConfig()
        assert config.disable_default_openrouter is False

    def test_disable_default_openrouter_can_be_set(self):
        """disable_default_openrouter can be explicitly set."""
        config = AuxiliaryRoutingConfig(disable_default_openrouter=True)
        assert config.disable_default_openrouter is True
