"""Property-based tests for replacement turn completion.

Feature: random-model-replacement
Properties: 13, 14, 22
Validates: Requirements 4.1, 4.2, 6.2
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
    turn_count: int = 1,
) -> ModelReplacementService:
    """Helper to create a test replacement service."""
    registry = BackendRegistry()
    registry.register_backend("test-backend", lambda: None)

    config = ReplacementConfig(
        enabled=True,
        probability=0.5,
        backend_model="test-backend:test-model",
        turn_count=turn_count,
    )

    return ModelReplacementService(config, registry)


@given(
    turn_count=st.integers(min_value=1, max_value=10),
    original_backend=st.text(min_size=1, max_size=20).filter(
        lambda x: x.replace("-", "").isalnum()
    ),
    original_model=st.text(min_size=1, max_size=20).filter(
        lambda x: x.replace("-", "").isalnum()
    ),
)
@property_test_settings(
    max_examples=15, suppress_health_check=[HealthCheck.filter_too_much]
)
def test_property_22_deactivation_logging(
    turn_count: int,
    original_backend: str,
    original_model: str,
) -> None:
    """
    Property 22: Deactivation logging.

    When replacement mode is deactivated (turns expire), an INFO log message
    must be emitted indicating the session_id and return to original model.

    Validates: Requirements 6.2
    """
    service = create_test_service(turn_count=turn_count)
    session_id = "test-session"

    # Activate replacement
    import asyncio

    asyncio.run(
        service.activate_replacement(session_id, original_backend, original_model)
    )

    # Create a mock logger
    original_logger = logging.getLogger("src.core.services.model_replacement_service")
    original_info = original_logger.info
    log_calls = []

    def capture_info(msg: str, *args, **kwargs) -> None:
        log_calls.append(msg)
        original_info(msg, *args, **kwargs)

    original_logger.info = capture_info

    try:
        # Complete turns until deactivation
        for _ in range(turn_count):
            service.complete_turn(session_id)

        # Verify deactivation log
        deactivation_logs = [
            log for log in log_calls if "Replacement deactivated" in log
        ]
        assert len(deactivation_logs) > 0, "No deactivation log emitted"

        log_message = deactivation_logs[0]
        assert session_id in log_message, f"Log missing session_id: {log_message}"
        assert (
            f"{original_backend}:{original_model}" in log_message
        ), f"Log missing original pair: {log_message}"

    finally:
        original_logger.info = original_info


@given(
    turn_count=st.integers(min_value=1, max_value=10),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
def test_property_13_14_turn_decrement_and_expiry(
    turn_count: int,
) -> None:
    """
    Properties 13 & 14: Turn counter decrement and expiry via service.

    Validates: Requirements 4.1, 4.2
    """
    service = create_test_service(turn_count=turn_count)
    session_id = "test-session"

    import asyncio

    asyncio.run(service.activate_replacement(session_id, "orig-back", "orig-mod"))

    state = service.get_state(session_id)

    # Check decrement
    for i in range(turn_count):
        expected_remaining = turn_count - i
        assert state.turns_remaining == expected_remaining
        assert state.active is True

        service.complete_turn(session_id)

    # Check expiry
    assert state.active is False
    assert state.turns_remaining == 0
