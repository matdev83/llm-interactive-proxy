"""Property-based tests for replacement activation.

Feature: random-model-replacement
Properties: 11, 21
Validates: Requirements 3.4, 6.1
"""

from __future__ import annotations

import logging

from hypothesis import HealthCheck, given
from hypothesis import strategies as st
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.services.backend_registry import BackendRegistry
from src.core.services.model_replacement_service import ModelReplacementService
from tests.utils.hypothesis_config import property_test_settings


def create_test_service(
    probability: float = 0.5,
    backend_model: str = "test-backend:test-model",
    turn_count: int = 1,
) -> ModelReplacementService:
    """Helper to create a test replacement service."""
    registry = BackendRegistry()

    def mock_factory() -> None:
        pass

    # Register the test backend
    backend_name = backend_model.split(":", 1)[0]
    registry.register_backend(backend_name, mock_factory)

    config = ReplacementConfig(
        enabled=True,
        probability=probability,
        backend_model=backend_model,
        turn_count=turn_count,
    )

    return ModelReplacementService(config, registry)


@given(
    turn_count=st.integers(min_value=1, max_value=100),
    original_backend=st.text(min_size=1, max_size=20).filter(
        lambda x: x.replace("-", "").isalnum()
    ),
    original_model=st.text(min_size=1, max_size=20).filter(
        lambda x: x.replace("-", "").isalnum()
    ),
)
@property_test_settings(
    suppress_health_check=[HealthCheck.filter_too_much], max_examples=20
)
def test_property_11_turn_counter_initialization(
    turn_count: int,
    original_backend: str,
    original_model: str,
) -> None:
    """
    Property 11: Turn counter initialization.

    When replacement is activated, the turn counter must be initialized to the
    configured replacement_turn_count value.

    Validates: Requirements 3.4
    """

    def mock_factory() -> None:
        pass

    registry = BackendRegistry()
    registry.register_backend("test-backend", mock_factory)

    config = ReplacementConfig(
        enabled=True,
        probability=0.5,
        backend_model="test-backend:test-model",
        turn_count=turn_count,
    )

    service = ModelReplacementService(config, registry)
    session_id = "test-session"

    # Activate replacement
    import asyncio

    asyncio.run(
        service.activate_replacement(session_id, original_backend, original_model)
    )

    # Verify state
    state = service.get_state(session_id)
    assert state.active is True, "State should be active after activation"
    assert state.turns_remaining == turn_count, (
        f"Turn counter should be initialized to {turn_count}, "
        f"got {state.turns_remaining}"
    )


@given(
    turn_count=st.integers(min_value=1, max_value=100),
    original_backend=st.text(min_size=1, max_size=20).filter(
        lambda x: x.replace("-", "").isalnum()
    ),
    original_model=st.text(min_size=1, max_size=20).filter(
        lambda x: x.replace("-", "").isalnum()
    ),
    replacement_backend_model=st.text(min_size=1, max_size=20).filter(
        lambda x: ":" in x
    ),
)
@property_test_settings(
    max_examples=20, suppress_health_check=[HealthCheck.filter_too_much]  # Reduced from 50 for performance
)
async def test_property_21_activation_logging(
    turn_count: int,
    original_backend: str,
    original_model: str,
    replacement_backend_model: str,
) -> None:
    """
    Property 21: Activation logging.

    When replacement is activated, an INFO log message must be emitted
    indicating the session_id, original model, replacement model, and turn count.

    Validates: Requirements 6.1
    """
    # Ensure valid format for replacement backend:model
    if ":" not in replacement_backend_model:
        replacement_backend_model = f"test-backend:{replacement_backend_model}"

    backend_name = replacement_backend_model.split(":", 1)[0]
    if not backend_name or not backend_name.replace("-", "").replace("_", "").isalnum():
        replacement_backend_model = "test-backend:test-model"

    def mock_factory() -> None:
        pass

    # Register the test backend
    test_backend_name = replacement_backend_model.split(":", 1)[0]
    registry = BackendRegistry()
    registry.register_backend(test_backend_name, mock_factory)

    config = ReplacementConfig(
        enabled=True,
        probability=0.5,
        backend_model=replacement_backend_model,
        turn_count=turn_count,
    )

    service = ModelReplacementService(config, registry)
    session_id = "test-session"

    # Create a mock logger to capture log calls
    original_logger = logging.getLogger("src.core.services.model_replacement_service")
    original_info = original_logger.info

    # Track log calls
    log_calls = []

    def capture_info(msg: str, *args, **kwargs) -> None:
        log_calls.append(msg)
        original_info(msg, *args, **kwargs)

    original_logger.info = capture_info

    try:
        # Activate replacement (async test, no need for asyncio.run)
        await service.activate_replacement(session_id, original_backend, original_model)

        # Verify INFO log was emitted
        activation_logs = [log for log in log_calls if "Replacement activated" in log]
        assert len(activation_logs) > 0, "No activation log emitted"

        log_message = activation_logs[0]
        assert session_id in log_message, f"Log missing session_id: {log_message}"
        assert (
            f"{original_backend}:{original_model}" in log_message
        ), f"Log missing original pair: {log_message}"
        assert (
            replacement_backend_model in log_message
        ), f"Log missing replacement pair: {log_message}"
        assert str(turn_count) in log_message, f"Log missing turn count: {log_message}"

    finally:
        original_logger.info = original_info
