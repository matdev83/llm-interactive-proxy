"""Unit tests for model replacement service error handling.

This module tests error handling for:
- Backend unavailability fallback
- State corruption recovery
- Configuration error handling
"""

import pytest
from pydantic import ValidationError
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.replacement_state import ReplacementState
from src.core.services.model_replacement_service import ModelReplacementService


class MockBackendRegistry:
    """Mock backend registry for testing."""

    def __init__(self, backends: list[str]):
        """Initialize with list of available backends."""
        self._backends = backends

    def get_registered_backends(self) -> list[str]:
        """Return list of registered backends."""
        return self._backends


class TestBackendUnavailableFallback:
    """Test fallback behavior when replacement backend becomes unavailable."""

    def test_fallback_when_backend_removed(self):
        """Test that service falls back to original when replacement backend is removed."""
        # Setup: Create service with replacement backend available
        config = ReplacementConfig(
            enabled=True,
            probability=1.0,
            backend_model="test-backend:test-model",
            turn_count=3,
        )
        registry = MockBackendRegistry(["original-backend", "test-backend"])
        service = ModelReplacementService(config, registry)

        # Activate replacement
        session_id = "test-session"

        # Manually activate replacement state
        state = service.get_state(session_id)
        state.activate(
            turn_count=3,
            original_backend="original-backend",
            original_model="original-model",
            replacement_backend="test-backend",
            replacement_model="test-model",
        )

        # Verify replacement is active
        assert state.active
        assert state.turns_remaining == 3

        # Simulate backend being removed
        registry._backends = ["original-backend"]

        # Get effective backend - should fall back to original
        backend, model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )

        # Verify fallback occurred
        assert backend == "original-backend"
        assert model == "original-model"

        # Verify replacement was deactivated
        assert not state.active
        assert state.turns_remaining == 0

    def test_fallback_on_registry_error(self):
        """Test that service falls back to original when registry throws error."""
        config = ReplacementConfig(
            enabled=True,
            probability=1.0,
            backend_model="test-backend:test-model",
            turn_count=3,
        )

        # Create registry that will throw error
        class ErrorRegistry:
            def get_registered_backends(self):
                raise RuntimeError("Registry error")

        registry = ErrorRegistry()
        service = ModelReplacementService(
            config, MockBackendRegistry(["original-backend", "test-backend"])
        )
        service._backend_registry = registry

        # Activate replacement
        session_id = "test-session"
        state = service.get_state(session_id)
        state.activate(
            turn_count=3,
            original_backend="original-backend",
            original_model="original-model",
            replacement_backend="test-backend",
            replacement_model="test-model",
        )

        # Get effective backend - should fall back to original despite error
        backend, model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )

        # Verify fallback occurred
        assert backend == "original-backend"
        assert model == "original-model"

        # Verify replacement was deactivated
        assert not state.active


class TestStateCorruptionRecovery:
    """Test recovery from corrupted replacement state."""

    def test_recovery_from_active_with_zero_turns(self):
        """Test recovery when state is active but turns_remaining is 0."""
        config = ReplacementConfig(
            enabled=True,
            probability=1.0,
            backend_model="test-backend:test-model",
            turn_count=3,
        )
        registry = MockBackendRegistry(["original-backend", "test-backend"])
        service = ModelReplacementService(config, registry)

        session_id = "test-session"

        # Create corrupted state: active but no turns remaining
        corrupted_state = ReplacementState()
        corrupted_state.active = True
        corrupted_state.turns_remaining = 0
        corrupted_state.original_backend = "original-backend"
        corrupted_state.original_model = "original-model"
        corrupted_state.replacement_backend = "test-backend"
        corrupted_state.replacement_model = "test-model"

        service._session_states[session_id] = corrupted_state

        # Get state - should detect corruption and reset
        state = service.get_state(session_id)

        # Verify state was reset
        assert not state.active
        assert state.turns_remaining == 0
        assert state.original_backend == ""
        assert state.original_model == ""

    def test_recovery_from_active_with_negative_turns(self):
        """Test recovery when state has negative turns_remaining."""
        config = ReplacementConfig(
            enabled=True,
            probability=1.0,
            backend_model="test-backend:test-model",
            turn_count=3,
        )
        registry = MockBackendRegistry(["original-backend", "test-backend"])
        service = ModelReplacementService(config, registry)

        session_id = "test-session"

        # Create corrupted state: negative turns
        corrupted_state = ReplacementState()
        corrupted_state.active = True
        corrupted_state.turns_remaining = -1
        corrupted_state.original_backend = "original-backend"
        corrupted_state.original_model = "original-model"
        corrupted_state.replacement_backend = "test-backend"
        corrupted_state.replacement_model = "test-model"

        service._session_states[session_id] = corrupted_state

        # Get state - should detect corruption and reset
        state = service.get_state(session_id)

        # Verify state was reset
        assert not state.active
        assert state.turns_remaining == 0

    def test_recovery_from_active_with_missing_backend_info(self):
        """Test recovery when state is active but missing backend information."""
        config = ReplacementConfig(
            enabled=True,
            probability=1.0,
            backend_model="test-backend:test-model",
            turn_count=3,
        )
        registry = MockBackendRegistry(["original-backend", "test-backend"])
        service = ModelReplacementService(config, registry)

        session_id = "test-session"

        # Create corrupted state: active but missing backend info
        corrupted_state = ReplacementState()
        corrupted_state.active = True
        corrupted_state.turns_remaining = 3
        corrupted_state.original_backend = ""  # Missing
        corrupted_state.original_model = ""  # Missing
        corrupted_state.replacement_backend = "test-backend"
        corrupted_state.replacement_model = "test-model"

        service._session_states[session_id] = corrupted_state

        # Get state - should detect corruption and reset
        state = service.get_state(session_id)

        # Verify state was reset
        assert not state.active
        assert state.turns_remaining == 0

    def test_recovery_from_inactive_with_nonzero_turns(self):
        """Test recovery when state is inactive but has non-zero turns."""
        config = ReplacementConfig(
            enabled=True,
            probability=1.0,
            backend_model="test-backend:test-model",
            turn_count=3,
        )
        registry = MockBackendRegistry(["original-backend", "test-backend"])
        service = ModelReplacementService(config, registry)

        session_id = "test-session"

        # Create corrupted state: inactive but has turns
        corrupted_state = ReplacementState()
        corrupted_state.active = False
        corrupted_state.turns_remaining = 3  # Should be 0 when inactive

        service._session_states[session_id] = corrupted_state

        # Get state - should detect corruption and reset
        state = service.get_state(session_id)

        # Verify state was reset
        assert not state.active
        assert state.turns_remaining == 0


class TestConfigurationErrorHandling:
    """Test configuration error handling during initialization."""

    def test_invalid_probability_raises_error(self):
        """Test that invalid probability raises ValidationError with detailed message."""
        with pytest.raises(ValidationError) as exc_info:
            ReplacementConfig(
                enabled=True,
                probability=1.5,  # Invalid: > 1.0
                backend_model="test-backend:test-model",
                turn_count=3,
            )

        assert "probability" in str(exc_info.value).lower()

    def test_invalid_backend_model_format_raises_error(self):
        """Test that invalid backend:model format raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ReplacementConfig(
                enabled=True,
                probability=0.5,
                backend_model="invalid-format",  # Missing colon
                turn_count=3,
            )

        assert "backend:model" in str(exc_info.value).lower()

    def test_invalid_turn_count_raises_error(self):
        """Test that invalid turn count raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            ReplacementConfig(
                enabled=True,
                probability=0.5,
                backend_model="test-backend:test-model",
                turn_count=0,  # Invalid: must be >= 1
            )

        assert "turn_count" in str(exc_info.value).lower()

    def test_unregistered_backend_raises_error(self):
        """Test that unregistered backend raises ValueError with available backends."""
        config = ReplacementConfig(
            enabled=True,
            probability=0.5,
            backend_model="nonexistent-backend:test-model",
            turn_count=3,
        )
        registry = MockBackendRegistry(["backend1", "backend2"])

        with pytest.raises(ValueError) as exc_info:
            ModelReplacementService(config, registry)

        error_msg = str(exc_info.value)
        assert "nonexistent-backend" in error_msg
        assert "not registered" in error_msg.lower()
        assert "backend1" in error_msg
        assert "backend2" in error_msg

    def test_backend_validation_error_wrapped(self):
        """Test that errors during backend validation are wrapped with context."""
        config = ReplacementConfig(
            enabled=True,
            probability=0.5,
            backend_model="test-backend:test-model",
            turn_count=3,
        )

        # Create registry that throws error
        class ErrorRegistry:
            def get_registered_backends(self):
                raise RuntimeError("Registry error")

        registry = ErrorRegistry()

        with pytest.raises(ValueError) as exc_info:
            ModelReplacementService(config, registry)

        error_msg = str(exc_info.value)
        assert "failed to validate" in error_msg.lower()
