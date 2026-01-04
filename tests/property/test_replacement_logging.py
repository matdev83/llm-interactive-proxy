"""Property-based tests for replacement logging.

Feature: random-model-replacement
Properties: 23, 24, 25
Validates: Requirements 6.3, 6.4, 6.5
"""

from __future__ import annotations

import contextlib
import logging

from hypothesis import HealthCheck, given
from hypothesis import strategies as st
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.request_context import RequestContext
from src.core.services.backend_registry import BackendRegistry
from src.core.services.model_replacement_service import ModelReplacementService
from tests.utils.hypothesis_config import property_test_settings

_shared_registry = None


def get_shared_registry():
    """Get or create shared BackendRegistry instance."""
    global _shared_registry
    if _shared_registry is None:
        _shared_registry = BackendRegistry()
    return _shared_registry


def create_test_service(
    probability: float,
    backend_model: str = "test-backend:test-model",
    turn_count: int = 1,
    random_generator: callable | None = None,
    enabled: bool = True,
) -> ModelReplacementService:
    """Helper to create a test replacement service."""
    registry = get_shared_registry()

    def mock_factory() -> None:
        pass

    # Register the test backend (idempotent)
    backend_name = backend_model.split(":", 1)[0]
    with contextlib.suppress(ValueError):
        registry.register_backend(backend_name, mock_factory)

    config = ReplacementConfig(
        enabled=enabled,
        probability=probability,
        backend_model=backend_model,
        turn_count=turn_count,
    )

    return ModelReplacementService(config, registry, random_generator)


def create_test_context() -> RequestContext:
    """Helper to create a test request context."""
    return RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
    )


@given(
    enabled=st.booleans(),
    probability=st.floats(min_value=0.0, max_value=1.0),
    backend_model=st.text(min_size=1, max_size=50).filter(lambda x: ":" in x),
    turn_count=st.integers(min_value=1, max_value=100),
)
@property_test_settings(
    max_examples=8,  # Reduced from 10 for performance
    suppress_health_check=[HealthCheck.filter_too_much],
)
def test_property_25_configuration_loading_logging(
    enabled: bool,
    probability: float,
    backend_model: str,
    turn_count: int,
) -> None:
    """
    Property 25: Configuration loading logging.

    For any replacement service initialization, an INFO log message must be
    emitted summarizing the replacement configuration.

    Validates: Requirements 6.5
    """
    # Ensure backend_model has valid format
    if ":" not in backend_model:
        backend_model = f"test-backend:{backend_model}"

    # Split and validate backend name
    backend_name = backend_model.split(":", 1)[0]
    if not backend_name or not backend_name.replace("-", "").replace("_", "").isalnum():
        backend_name = "test-backend"
        backend_model = f"{backend_name}:test-model"

    # Create registry and register backend
    registry = BackendRegistry()

    def mock_factory() -> None:
        pass

    registry.register_backend(backend_name, mock_factory)

    # Create configuration
    config = ReplacementConfig(
        enabled=enabled,
        probability=probability,
        backend_model=backend_model,
        turn_count=turn_count,
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
        # Initialize service - this should log configuration
        ModelReplacementService(config, registry)

        # Verify INFO log was emitted
        assert len(log_calls) > 0, "No INFO log emitted during initialization"

        # Verify log contains configuration details
        log_message = log_calls[0]
        assert (
            "Model replacement service initialized" in log_message
        ), f"Log message missing initialization text: {log_message}"
        assert (
            f"enabled={enabled}" in log_message
        ), f"Log message missing enabled status: {log_message}"
        assert (
            f"probability={probability}" in log_message
        ), f"Log message missing probability: {log_message}"
        assert (
            f"backend_model={backend_model}" in log_message
        ), f"Log message missing backend_model: {log_message}"
        assert (
            f"turn_count={turn_count}" in log_message
        ), f"Log message missing turn_count: {log_message}"
    finally:
        # Restore original logger
        original_logger.info = original_info


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=100),
    random_value=st.floats(min_value=0.0, max_value=1.0),
)
@property_test_settings(
    max_examples=20, suppress_health_check=[HealthCheck.filter_too_much]
)  # Reduced from 30 for performance
def test_property_24_probability_check_logging(
    probability: float,
    turn_count: int,
    random_value: float,
) -> None:
    """
    Property 24: Probability check logging.

    For any replacement probability evaluation, a DEBUG log message must be
    emitted containing session_id, generated random value, and probability
    threshold.

    Validates: Requirements 6.4
    """

    # Create service with deterministic random generator
    def deterministic_random() -> float:
        return random_value

    service = create_test_service(
        probability=probability,
        turn_count=turn_count,
        random_generator=deterministic_random,
    )
    context = create_test_context()

    # Create a mock logger to capture debug log calls
    original_logger = logging.getLogger("src.core.services.model_replacement_service")
    original_level = original_logger.level
    original_debug = original_logger.debug

    # Track debug log calls
    debug_calls = []

    def capture_debug(msg: str, *args, **kwargs) -> None:
        debug_calls.append(msg)
        original_debug(msg, *args, **kwargs)

    # Enable DEBUG level and set capture
    original_logger.setLevel(logging.DEBUG)
    original_logger.debug = capture_debug

    try:
        # Perform probability check
        session_id = "test-session"
        service.should_replace(session_id, context)

        # Verify DEBUG log was emitted
        assert len(debug_calls) > 0, "No DEBUG log emitted during probability check"

        # Find the probability check log message
        prob_check_logs = [
            log for log in debug_calls if "Replacement probability check" in log
        ]
        assert len(prob_check_logs) > 0, "No probability check log found in debug logs"

        # Verify log contains required details
        log_message = prob_check_logs[0]
        assert (
            session_id in log_message
        ), f"Log message missing session_id: {log_message}"
        assert (
            f"random={random_value:.4f}" in log_message
        ), f"Log message missing random value: {log_message}"
        assert (
            f"threshold={probability:.4f}" in log_message
        ), f"Log message missing threshold: {log_message}"

        # Verify activation result is logged
        expected_activate = random_value < probability
        assert (
            f"activate={expected_activate}" in log_message
        ), f"Log message missing activation result: {log_message}"
    finally:
        # Restore original logger
        original_logger.debug = original_debug
        original_logger.setLevel(original_level)


def _is_valid_identifier(text: str) -> bool:
    """Check if text is a valid identifier (alphanumeric with dashes/underscores)."""
    return text.replace("-", "").replace("_", "").isalnum()


@given(
    probability=st.floats(min_value=0.0, max_value=1.0),
    turn_count=st.integers(min_value=1, max_value=100),
    original_backend=st.text(min_size=1, max_size=20).filter(_is_valid_identifier),
    original_model=st.text(min_size=1, max_size=20).filter(_is_valid_identifier),
)
@property_test_settings(
    max_examples=10, suppress_health_check=[HealthCheck.filter_too_much]
)
def test_property_23_routing_logging(
    probability: float,
    turn_count: int,
    original_backend: str,
    original_model: str,
) -> None:
    """
    Property 23: Routing logging.

    For any request routed to a replacement model, a DEBUG log message must be
    emitted containing session_id and replacement backend:model.

    Validates: Requirements 6.3
    """
    # Create service with probability=1.0 to ensure replacement activates
    service = create_test_service(
        probability=1.0,
        turn_count=turn_count,
    )
    context = create_test_context()

    # Create a mock logger to capture debug log calls
    original_logger = logging.getLogger("src.core.services.model_replacement_service")
    original_level = original_logger.level
    original_debug = original_logger.debug

    # Track debug log calls
    debug_calls = []

    def capture_debug(msg: str, *args, **kwargs) -> None:
        debug_calls.append(msg)
        original_debug(msg, *args, **kwargs)

    # Enable DEBUG level and set capture
    original_logger.setLevel(logging.DEBUG)
    original_logger.debug = capture_debug

    try:
        # Activate replacement
        session_id = "test-session"
        should_replace = service.should_replace(session_id, context)
        assert should_replace, "Replacement should activate with probability=1.0"

        # Activate the replacement
        import asyncio

        asyncio.run(
            service.activate_replacement(session_id, original_backend, original_model)
        )

        # Clear previous debug calls
        debug_calls.clear()

        # Get effective backend:model - this should log routing decision
        service.get_effective_backend_model(
            session_id, original_backend, original_model
        )

        # Verify DEBUG log was emitted
        assert len(debug_calls) > 0, "No DEBUG log emitted during routing"

        # Find the routing log message
        routing_logs = [log for log in debug_calls if "Using replacement model" in log]
        assert len(routing_logs) > 0, "No routing log found in debug logs"

        # Verify log contains required details
        log_message = routing_logs[0]
        assert (
            session_id in log_message
        ), f"Log message missing session_id: {log_message}"

        # Verify replacement backend:model is logged
        assert (
            "test-backend:test-model" in log_message
        ), f"Log message missing replacement backend:model: {log_message}"
    finally:
        # Restore original logger
        original_logger.debug = original_debug
        original_logger.setLevel(original_level)
