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
    suppress_health_check=[HealthCheck.filter_too_much],
    max_examples=10,  # Reduced from 20 for performance
)
def test_property_11_turn_counter_initialization(
    turn_count: int,
    original_backend: str,
    original_model: str,
) -> None:
    """
    Property 11: Turn counter initialization.

    When replacement is activated with a different model, the turn counter
    must be initialized to the configured replacement_turn_count value.
    When replacement model is the same as original, activation is skipped.

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

    # Check if replacement would be same as original
    is_same_model = (
        original_backend == "test-backend" and original_model == "test-model"
    )

    # Activate replacement
    import asyncio

    asyncio.run(
        service.activate_replacement(session_id, original_backend, original_model)
    )

    # Verify state
    state = service.get_state(session_id)

    if is_same_model:
        # When models are the same, activation should be skipped
        assert not state.active, "State should not be active when models are the same"
        assert (
            state.turns_remaining == 0
        ), "Turns remaining should be 0 when models are the same"
    else:
        # When models are different, activation should proceed normally
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
    # Build backend:model explicitly to avoid filter_too_much (":" rarely in random text)
    replacement_backend_model=st.builds(
        lambda b, m: f"{b}:{m}",
        b=st.text(min_size=1, max_size=10).filter(
            lambda x: x.replace("-", "").replace("_", "").isalnum()
        ),
        m=st.text(min_size=1, max_size=10).filter(
            lambda x: x.replace("-", "").replace("_", "").isalnum()
        ),
    ),
)
@property_test_settings(
    max_examples=6,  # Reduced for performance while preserving coverage
    suppress_health_check=[HealthCheck.filter_too_much],
)
async def test_property_21_activation_logging(
    turn_count: int,
    original_backend: str,
    original_model: str,
    replacement_backend_model: str,
) -> None:
    """
    Property 21: Activation logging.

    When replacement is activated with a different model, an INFO log message
    must be emitted indicating the session_id, original model, replacement model,
    and turn count. When replacement model is the same as original, no activation
    occurs and no log is emitted.

    Validates: Requirements 6.1
    """
    # Ensure valid format for replacement backend:model
    if ":" not in replacement_backend_model:
        replacement_backend_model = f"test-backend:{replacement_backend_model}"

    parts = replacement_backend_model.split(":", 1)
    backend_name = parts[0]
    model_name = parts[1] if len(parts) > 1 else ""

    # Validate backend name
    if not backend_name or not backend_name.replace("-", "").replace("_", "").isalnum():
        backend_name = "test-backend"

    # Validate model name
    if not model_name or not model_name.replace("-", "").replace("_", "").isalnum():
        model_name = "test-model"

    replacement_backend_model = f"{backend_name}:{model_name}"

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

    # Check if replacement would be same as original
    replacement_parts = replacement_backend_model.split(":", 1)
    is_same_model = (
        replacement_parts[0] == original_backend
        and replacement_parts[1] == original_model
    )

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

        if is_same_model:
            # When replacement model is same as original, no activation should occur
            activation_logs = [
                log for log in log_calls if "Replacement activated" in log
            ]
            assert (
                len(activation_logs) == 0
            ), "Activation log should not be emitted when replacement model is same as original"

            # Verify state remains inactive
            state = service.get_state(session_id)
            assert (
                not state.active
            ), "State should not be active when models are the same"
        else:
            # When replacement model is different, activation should occur with log
            activation_logs = [
                log for log in log_calls if "Replacement activated" in log
            ]
            assert len(activation_logs) > 0, "No activation log emitted"

            log_message = activation_logs[0]
            assert session_id in log_message, f"Log missing session_id: {log_message}"
            assert (
                f"{original_backend}:{original_model}" in log_message
            ), f"Log missing original pair: {log_message}"
            assert (
                replacement_backend_model in log_message
            ), f"Log missing replacement pair: {log_message}"
            assert (
                str(turn_count) in log_message
            ), f"Log missing turn count: {log_message}"

    finally:
        original_logger.info = original_info
