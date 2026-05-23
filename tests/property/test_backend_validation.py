"""Property-based tests for backend validation in model replacement service.

Feature: random-model-replacement
Property: 4
Validates: Requirements 2.4
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given
from hypothesis import strategies as st
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.services.backend_registry import BackendRegistry
from src.core.services.model_replacement_service import ModelReplacementService
from tests.utils.hypothesis_config import property_test_settings


# Strategy for generating valid backend:model strings
@st.composite
def backend_model_strategy(draw: st.DrawFn) -> str:
    """Generate valid backend:model format strings."""
    backend = draw(
        st.text(
            min_size=1,
            max_size=20,
            alphabet=st.characters(
                whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_"
            ),
        )
    )
    model = draw(
        st.text(
            min_size=1,
            max_size=20,
            alphabet=st.characters(
                whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_."
            ),
        )
    )
    return f"{backend}:{model}"


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    backend_model=backend_model_strategy(),
    turn_count=st.integers(min_value=1, max_value=100),
)
@property_test_settings(
    max_examples=20, suppress_health_check=[HealthCheck.filter_too_much]
)
def test_property_4_registered_backend_validation(
    probability: float, backend_model: str, turn_count: int
) -> None:
    """
    Property 4: Registered backend validation.

    For any ReplacementConfig with enabled=True, the backend portion of
    backend_model must exist in the backend registry.

    Validates: Requirements 2.4
    """
    # Create a backend registry with some registered backends
    registry = BackendRegistry()

    # Register some test backends
    def mock_factory() -> None:
        pass

    registry.register_backend("test-backend-1", mock_factory)
    registry.register_backend("test-backend-2", mock_factory)
    registry.register_backend("anthropic", mock_factory)
    registry.register_backend("openai", mock_factory)

    # Parse the backend from the generated backend_model
    backend_name = backend_model.split(":", 1)[0]

    # Create configuration
    config = ReplacementConfig(
        enabled=True,
        probability=probability,
        backend_model=backend_model,
        turn_count=turn_count,
    )

    # Get list of registered backends
    registered_backends = registry.get_registered_backends()

    if backend_name in registered_backends:
        # If backend is registered, service initialization should succeed
        service = ModelReplacementService(config, registry)
        assert service is not None
    else:
        # If backend is not registered, service initialization should fail
        with pytest.raises(ValueError) as exc_info:
            ModelReplacementService(config, registry)

        # Check that error message mentions the unregistered backend
        error_msg = str(exc_info.value)
        assert backend_name in error_msg
        assert "not registered" in error_msg.lower()


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=100),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
def test_property_4_unregistered_backend_fails(
    probability: float, turn_count: int
) -> None:
    """
    Property 4: Unregistered backend validation failure.

    For any ReplacementConfig with enabled=True and an unregistered backend,
    service initialization must raise ValueError.

    Validates: Requirements 2.4
    """
    # Create an empty backend registry
    registry = BackendRegistry()

    # Use a backend that is definitely not registered
    backend_model = "definitely-not-registered-backend:some-model"

    # Create configuration
    config = ReplacementConfig(
        enabled=True,
        probability=probability,
        backend_model=backend_model,
        turn_count=turn_count,
    )

    # Service initialization should fail
    with pytest.raises(ValueError) as exc_info:
        ModelReplacementService(config, registry)

    # Check that error message is descriptive
    error_msg = str(exc_info.value)
    assert "definitely-not-registered-backend" in error_msg
    assert "not registered" in error_msg.lower()


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=100),
    registered_backend=st.sampled_from(["anthropic", "openai", "gemini", "qwen-oauth"]),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
def test_property_4_registered_backend_succeeds(
    probability: float, turn_count: int, registered_backend: str
) -> None:
    """
    Property 4: Registered backend validation success.

    For any ReplacementConfig with enabled=True and a registered backend,
    service initialization must succeed.

    Validates: Requirements 2.4
    """
    # Create a backend registry and register the backend
    registry = BackendRegistry()

    def mock_factory() -> None:
        pass

    registry.register_backend(registered_backend, mock_factory)

    # Create configuration with the registered backend
    backend_model = f"{registered_backend}:test-model"
    config = ReplacementConfig(
        enabled=True,
        probability=probability,
        backend_model=backend_model,
        turn_count=turn_count,
    )

    # Service initialization should succeed
    service = ModelReplacementService(config, registry)
    assert service is not None


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    backend_model=backend_model_strategy(),
    turn_count=st.integers(min_value=1, max_value=100),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
def test_disabled_config_skips_backend_validation(
    probability: float, backend_model: str, turn_count: int
) -> None:
    """
    Test that disabled configuration skips backend validation.

    When enabled=False, service initialization should succeed regardless of
    whether the backend is registered.
    """
    # Create an empty backend registry
    registry = BackendRegistry()

    # Create disabled configuration
    config = ReplacementConfig(
        enabled=False,
        probability=probability,
        backend_model=backend_model,
        turn_count=turn_count,
    )

    # Service initialization should succeed even with unregistered backend
    service = ModelReplacementService(config, registry)
    assert service is not None
