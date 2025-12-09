"""Unit tests for Gemini fallback logic.

Note: As of the Resilience Layer implementation, automatic model fallbacks
(e.g., Pro -> Flash) are disabled in connectors. Error handling and recovery
are now handled by the Resilience Layer at the BackendService level.
"""

from unittest.mock import MagicMock

from src.connectors.gemini_base.graceful_degradation import (
    DEFAULT_FALLBACK_MAP,
    GracefulDegradationManager,
    get_fallback_model,
)


class TestGeminiFallbackLogicDisabled:
    """Tests verifying that fallback logic is now disabled."""

    def test_default_fallback_map_is_empty(self):
        """Test that the default fallback map is empty (fallbacks disabled)."""
        assert DEFAULT_FALLBACK_MAP == {}

    def test_get_fallback_model_returns_none(self):
        """Test that get_fallback_model returns None for all models."""
        assert get_fallback_model("gemini-3-pro") is None
        assert get_fallback_model("gemini-2.5-pro") is None
        assert get_fallback_model("gemini-1.5-pro") is None

    def test_manager_get_models_to_try_no_fallbacks(self):
        """Test that GracefulDegradationManager returns only original model."""
        manager = GracefulDegradationManager(MagicMock())
        models = manager.get_models_to_try("gemini-3-pro")
        # Should only contain the original model, no fallbacks
        assert models == ["gemini-3-pro"]

    def test_manager_get_models_to_try_single_model(self):
        """Test that get_models_to_try returns single model for any input."""
        manager = GracefulDegradationManager(MagicMock())
        models = manager.get_models_to_try("gemini-2.5-pro")
        # Should only contain the original model, no fallbacks
        assert models == ["gemini-2.5-pro"]

    def test_custom_fallback_map_can_be_provided(self):
        """Test that custom fallback maps can still be used if needed."""
        custom_map = {"model-a": "model-b"}
        result = get_fallback_model("model-a", fallback_map=custom_map)
        assert result == "model-b"
