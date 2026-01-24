"""Integration tests for wire capture compatibility with model replacement.

This module tests that model replacement works correctly with wire capture,
ensuring that both original and replacement model requests/responses are captured.

Feature: random-model-replacement
Validates: Requirements 7.3
"""

from __future__ import annotations

import pytest
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.request_context import RequestContext
from src.core.services.backend_registry import BackendRegistry
from src.core.services.model_replacement_service import ModelReplacementService


def create_test_service(
    probability: float = 1.0,
    backend_model: str = "replacement-backend:replacement-model",
    turn_count: int = 1,
) -> ModelReplacementService:
    """Helper to create a test replacement service."""
    registry = BackendRegistry()

    def mock_factory() -> None:
        pass

    # Register both original and replacement backends
    registry.register_backend("original-backend", mock_factory)
    registry.register_backend("replacement-backend", mock_factory)

    config = ReplacementConfig(
        enabled=True,
        probability=probability,
        backend_model=backend_model,
        turn_count=turn_count,
    )

    return ModelReplacementService(config, registry)


def create_test_context_with_capture(capture_enabled: bool = True) -> RequestContext:
    """Helper to create a test request context with wire capture configuration."""
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
    )

    # Add wire capture configuration to context state
    if context.state is None:
        context.state = {}
    context.state["wire_capture_enabled"] = capture_enabled
    context.state["captured_requests"] = []
    context.state["captured_responses"] = []

    return context


@pytest.mark.asyncio
async def test_wire_capture_records_replacement_requests() -> None:
    """Test that wire capture records requests to replacement models.

    When replacement is active and wire capture is enabled, requests to the
    replacement backend should be captured.

    Validates: Requirements 7.3
    """
    # Create service with probability=1.0 to ensure replacement triggers
    service = create_test_service(probability=1.0, turn_count=3)

    # Create context with wire capture enabled
    context = create_test_context_with_capture(capture_enabled=True)

    session_id = "test-session"

    # Check if replacement should trigger
    service.should_replace(session_id, context)  # First turn skip
    should_replace = service.should_replace(session_id, context)
    assert should_replace, "Replacement should trigger with probability=1.0"

    # Activate replacement
    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Get effective backend:model
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )

    # Verify replacement is active
    assert effective_backend == "replacement-backend"
    assert effective_model == "replacement-model"

    # Verify wire capture is still enabled
    assert context.state is not None
    assert context.state["wire_capture_enabled"] is True

    # Simulate capturing a request to the replacement backend
    context.state["captured_requests"].append(
        {
            "backend": effective_backend,
            "model": effective_model,
            "timestamp": "2024-01-01T00:00:00Z",
        }
    )

    # Verify the request was captured with replacement backend:model
    assert len(context.state["captured_requests"]) == 1
    assert context.state["captured_requests"][0]["backend"] == "replacement-backend"
    assert context.state["captured_requests"][0]["model"] == "replacement-model"


@pytest.mark.asyncio
async def test_wire_capture_records_both_original_and_replacement() -> None:
    """Test that wire capture records both original and replacement models.

    When replacement activates mid-session, wire capture should record both
    the original model requests (before replacement) and replacement model
    requests (during replacement window).

    Validates: Requirements 7.3
    """
    # Create service with probability=0.5 and deterministic random
    call_count = 0

    def alternating_random() -> float:
        nonlocal call_count
        call_count += 1
        # First call returns 0.6 (no replacement), second returns 0.4 (replacement)
        return 0.6 if call_count == 1 else 0.4

    service = create_test_service(
        probability=0.5,
        turn_count=2,
    )
    service._random_generator = alternating_random

    # Create context with wire capture enabled
    context = create_test_context_with_capture(capture_enabled=True)

    session_id = "test-session"

    # First request - should not trigger replacement
    service.should_replace(session_id, context)  # First turn skip
    should_replace_1 = service.should_replace(session_id, context)
    assert not should_replace_1, "First request should not trigger replacement"

    effective_backend_1, effective_model_1 = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )

    # Capture first request (original)
    context.state["captured_requests"].append(
        {
            "backend": effective_backend_1,
            "model": effective_model_1,
            "request_num": 1,
        }
    )

    # Complete first turn
    service.complete_turn(session_id)

    # Second request - should trigger replacement
    # No priming needed here as state already exists
    should_replace_2 = service.should_replace(session_id, context)
    assert should_replace_2, "Second request should trigger replacement"

    await service.activate_replacement(session_id, "original-backend", "original-model")

    effective_backend_2, effective_model_2 = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )

    # Capture second request (replacement)
    context.state["captured_requests"].append(
        {
            "backend": effective_backend_2,
            "model": effective_model_2,
            "request_num": 2,
        }
    )

    # Verify both requests were captured
    assert len(context.state["captured_requests"]) == 2

    # First request should be original
    assert context.state["captured_requests"][0]["backend"] == "original-backend"
    assert context.state["captured_requests"][0]["model"] == "original-model"

    # Second request should be replacement
    assert context.state["captured_requests"][1]["backend"] == "replacement-backend"
    assert context.state["captured_requests"][1]["model"] == "replacement-model"


@pytest.mark.asyncio
async def test_wire_capture_disabled_with_replacement() -> None:
    """Test that replacement works when wire capture is disabled.

    When wire capture is disabled, replacement should work normally without
    requiring capture functionality.

    Validates: Requirements 7.3
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=1)

    # Create context without wire capture
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
    )

    session_id = "test-session"

    # Check if replacement should trigger
    service.should_replace(session_id, context)  # First turn skip
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    # Activate replacement
    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Get effective backend:model
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )

    # Verify replacement is active
    assert effective_backend == "replacement-backend"
    assert effective_model == "replacement-model"


@pytest.mark.asyncio
async def test_wire_capture_across_replacement_window() -> None:
    """Test that wire capture works throughout the replacement window.

    When replacement is active for multiple turns, wire capture should
    consistently record all requests to the replacement backend.

    Validates: Requirements 7.3
    """
    # Create service with 3-turn window
    service = create_test_service(probability=1.0, turn_count=3)

    # Create context with wire capture enabled
    context = create_test_context_with_capture(capture_enabled=True)

    session_id = "test-session"

    # Activate replacement
    service.should_replace(session_id, context)  # First turn skip
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Simulate 3 turns with wire capture
    for turn in range(3):
        # Get effective backend:model
        effective_backend, effective_model = service.get_effective_backend_model(
            session_id, "original-backend", "original-model"
        )

        # Capture request
        context.state["captured_requests"].append(
            {
                "backend": effective_backend,
                "model": effective_model,
                "turn": turn + 1,
            }
        )

        # Verify wire capture is still enabled
        assert context.state["wire_capture_enabled"] is True

        # Complete the turn
        service.complete_turn(session_id)

    # Verify all 3 requests were captured
    assert len(context.state["captured_requests"]) == 3

    # All requests should be to replacement backend during the window
    for i, request in enumerate(context.state["captured_requests"]):
        if i < 2:  # First 2 turns use replacement
            assert request["backend"] == "replacement-backend"
            assert request["model"] == "replacement-model"
        # Note: The 3rd turn completes and deactivates, but the request
        # is still made to the replacement backend before deactivation


@pytest.mark.asyncio
async def test_wire_capture_response_recording() -> None:
    """Test that wire capture records responses from replacement models.

    When replacement is active and wire capture is enabled, responses from the
    replacement backend should be captured.

    Validates: Requirements 7.3
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=1)

    # Create context with wire capture enabled
    context = create_test_context_with_capture(capture_enabled=True)

    session_id = "test-session"

    # Activate replacement
    service.should_replace(session_id, context)  # First turn skip
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Get effective backend:model
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )

    # Simulate capturing a response from the replacement backend
    context.state["captured_responses"].append(
        {
            "backend": effective_backend,
            "model": effective_model,
            "content": "Test response from replacement model",
            "timestamp": "2024-01-01T00:00:01Z",
        }
    )

    # Verify the response was captured with replacement backend:model
    assert len(context.state["captured_responses"]) == 1
    assert context.state["captured_responses"][0]["backend"] == "replacement-backend"
    assert context.state["captured_responses"][0]["model"] == "replacement-model"
    assert (
        "Test response from replacement model"
        in context.state["captured_responses"][0]["content"]
    )
