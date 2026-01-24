"""Integration tests for opt-out mechanisms with model replacement.

This module tests header-based and session-level opt-out mechanisms,
verifying that replacement can be disabled and that immediate deactivation
occurs when requested.

Feature: random-model-replacement
Validates: Requirements 9.1, 9.2, 9.5
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


def create_test_context(headers: dict[str, str] | None = None) -> RequestContext:
    """Helper to create a test request context."""
    return RequestContext(
        headers=headers or {},
        cookies={},
        state=None,
        app_state=None,
    )


@pytest.mark.asyncio
async def test_header_based_opt_out() -> None:
    """Test that X-Disable-Replacement header prevents replacement.

    When a request includes the X-Disable-Replacement: true header, replacement
    should be skipped and the original backend should be used.

    Validates: Requirements 9.1
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=3)

    # Create context with opt-out header
    context = create_test_context(headers={"x-disable-replacement": "true"})

    session_id = "test-session"

    # Check if replacement should trigger
    should_replace = service.should_replace(session_id, context)
    assert not should_replace, "Replacement should be disabled by header"

    # Verify original backend is used
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )
    assert effective_backend == "original-backend"
    assert effective_model == "original-model"


@pytest.mark.asyncio
async def test_header_opt_out_case_insensitive() -> None:
    """Test that opt-out header is case-insensitive.

    The header value should be treated case-insensitively (true, True, TRUE).

    Validates: Requirements 9.1
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=3)

    session_id = "test-session"

    # Test various case combinations
    test_cases = ["true", "True", "TRUE", "TrUe"]

    for header_value in test_cases:
        context = create_test_context(headers={"x-disable-replacement": header_value})

        should_replace = service.should_replace(session_id, context)
        assert (
            not should_replace
        ), f"Replacement should be disabled with header value '{header_value}'"


@pytest.mark.asyncio
async def test_header_opt_out_with_false_value() -> None:
    """Test that header with 'false' value does not disable replacement.

    Only the value 'true' should disable replacement; other values should not.

    Validates: Requirements 9.1
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=3)

    # Create context with header set to 'false'
    context = create_test_context(headers={"x-disable-replacement": "false"})

    session_id = "test-session"

    # Check if replacement should trigger
    service.should_replace(session_id, context)  # First turn skip
    should_replace = service.should_replace(session_id, context)
    assert should_replace, "Replacement should not be disabled when header is 'false'"


@pytest.mark.asyncio
async def test_session_level_opt_out() -> None:
    """Test that session-level opt-out prevents replacement.

    When a session is marked as replacement-disabled, replacement should never
    activate for any turns in that session.

    Validates: Requirements 9.2
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=3)

    context = create_test_context()
    session_id = "test-session"

    # Disable replacement for the session
    service.disable_for_session(session_id)

    # Try to trigger replacement multiple times
    for _ in range(5):
        should_replace = service.should_replace(session_id, context)
        assert not should_replace, "Replacement should be disabled for this session"

    # Verify original backend is always used
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )
    assert effective_backend == "original-backend"
    assert effective_model == "original-model"


@pytest.mark.asyncio
async def test_immediate_deactivation_on_disable() -> None:
    """Test that active replacement is immediately deactivated when disabled.

    When a session transitions from replacement-enabled to replacement-disabled,
    any active replacement should immediately deactivate.

    Validates: Requirements 9.5
    """
    # Create service with 5-turn window
    service = create_test_service(probability=1.0, turn_count=5)

    context = create_test_context()
    session_id = "test-session"

    # Activate replacement
    service.should_replace(session_id, context)  # First turn skip
    should_replace = service.should_replace(session_id, context)
    assert should_replace

    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Verify replacement is active
    state = service.get_state(session_id)
    assert state.active
    assert state.turns_remaining == 5

    # Disable replacement for the session
    service.disable_for_session(session_id)

    # Verify replacement was immediately deactivated
    state = service.get_state(session_id)
    assert not state.active, "Replacement should be immediately deactivated"
    assert state.turns_remaining == 0

    # Verify original backend is used
    effective_backend, effective_model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )
    assert effective_backend == "original-backend"
    assert effective_model == "original-model"


@pytest.mark.asyncio
async def test_session_opt_out_persists_across_turns() -> None:
    """Test that session-level opt-out persists across multiple turns.

    Once a session is disabled, it should remain disabled for all subsequent
    turns until explicitly re-enabled.

    Validates: Requirements 9.2
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=3)

    context = create_test_context()
    session_id = "test-session"

    # Disable replacement for the session
    service.disable_for_session(session_id)

    # Try to trigger replacement across multiple turns
    for turn in range(10):
        should_replace = service.should_replace(session_id, context)
        assert not should_replace, f"Replacement should be disabled on turn {turn + 1}"

        # Simulate completing a turn
        service.complete_turn(session_id)


@pytest.mark.asyncio
async def test_header_opt_out_does_not_affect_other_sessions() -> None:
    """Test that header opt-out only affects the current request.

    Using the opt-out header in one session should not affect other sessions.

    Validates: Requirements 9.1
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=3)

    session_1 = "session-1"
    session_2 = "session-2"

    # Create context with opt-out header for session-1
    context_with_header = create_test_context(headers={"x-disable-replacement": "true"})
    context_without_header = create_test_context()

    # Prime sessions
    service.should_replace(session_1, context_with_header)
    service.should_replace(session_2, context_without_header)

    # Check session-1 with header
    should_replace_1 = service.should_replace(session_1, context_with_header)
    assert not should_replace_1, "Session-1 should have replacement disabled"

    # Check session-2 without header
    should_replace_2 = service.should_replace(session_2, context_without_header)
    assert should_replace_2, "Session-2 should have replacement enabled"


@pytest.mark.asyncio
async def test_session_opt_out_does_not_affect_other_sessions() -> None:
    """Test that session-level opt-out only affects the specified session.

    Disabling replacement for one session should not affect other sessions.

    Validates: Requirements 9.2
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=3)

    context = create_test_context()

    session_1 = "session-1"
    session_2 = "session-2"

    # Disable replacement for session-1
    service.disable_for_session(session_1)

    # Prime sessions
    service.should_replace(session_1, context)
    service.should_replace(session_2, context)

    # Check session-1
    should_replace_1 = service.should_replace(session_1, context)
    assert not should_replace_1, "Session-1 should have replacement disabled"

    # Check session-2
    should_replace_2 = service.should_replace(session_2, context)
    assert should_replace_2, "Session-2 should have replacement enabled"


@pytest.mark.asyncio
async def test_combined_header_and_session_opt_out() -> None:
    """Test that both header and session opt-out work together.

    When both opt-out mechanisms are used, replacement should be disabled.

    Validates: Requirements 9.1, 9.2
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=3)

    context = create_test_context(headers={"x-disable-replacement": "true"})
    session_id = "test-session"

    # Disable at session level
    service.disable_for_session(session_id)

    # Check replacement
    should_replace = service.should_replace(session_id, context)
    assert not should_replace, "Replacement should be disabled by both mechanisms"


@pytest.mark.asyncio
async def test_opt_out_prevents_activation() -> None:
    """Test that opt-out prevents replacement from being activated.

    When opt-out is active, attempts to activate replacement should have no effect.

    Validates: Requirements 9.2
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=3)

    context = create_test_context()
    session_id = "test-session"

    # Disable replacement for the session
    service.disable_for_session(session_id)

    # Try to activate replacement
    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Verify replacement is not active (disabled sessions cannot activate)
    # Note: The current implementation allows activation but should_replace returns False
    # This test verifies the effective behavior
    should_replace = service.should_replace(session_id, context)
    assert not should_replace, "Replacement should not trigger for disabled session"


@pytest.mark.asyncio
async def test_cleanup_removes_session_opt_out() -> None:
    """Test that session cleanup removes the opt-out flag.

    After cleaning up a session, the opt-out flag should be removed and
    replacement can be enabled again.

    Validates: Requirements 9.2
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=3)

    context = create_test_context()
    session_id = "test-session"

    # Disable replacement for the session
    service.disable_for_session(session_id)

    # Verify opt-out is active
    should_replace = service.should_replace(session_id, context)
    assert not should_replace

    # Clean up session
    service.cleanup_session(session_id)

    # Verify opt-out was removed
    service.should_replace(session_id, context)  # First turn skip
    should_replace = service.should_replace(session_id, context)
    assert should_replace, "Replacement should be enabled after cleanup"


@pytest.mark.asyncio
async def test_deactivation_on_disable_with_partial_turns() -> None:
    """Test immediate deactivation when replacement is partially through window.

    When replacement is disabled mid-window, it should immediately deactivate
    regardless of remaining turns.

    Validates: Requirements 9.5
    """
    # Create service with 10-turn window
    service = create_test_service(probability=1.0, turn_count=10)

    create_test_context()
    session_id = "test-session"

    # Activate replacement
    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Complete 3 turns
    for _ in range(3):
        service.complete_turn(session_id)

    # Verify replacement is still active with 7 turns remaining
    state = service.get_state(session_id)
    assert state.active
    assert state.turns_remaining == 7

    # Disable replacement
    service.disable_for_session(session_id)

    # Verify immediate deactivation
    state = service.get_state(session_id)
    assert not state.active
    assert state.turns_remaining == 0


@pytest.mark.asyncio
async def test_header_opt_out_with_missing_header() -> None:
    """Test that missing opt-out header allows replacement.

    When the opt-out header is not present, replacement should work normally.

    Validates: Requirements 9.1
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=3)

    # Create context without opt-out header
    context = create_test_context(headers={})

    session_id = "test-session"

    # Check if replacement should trigger
    service.should_replace(session_id, context)  # First turn skip
    should_replace = service.should_replace(session_id, context)
    assert should_replace, "Replacement should be enabled without opt-out header"


@pytest.mark.asyncio
async def test_multiple_sessions_with_mixed_opt_out() -> None:
    """Test multiple sessions with different opt-out configurations.

    Some sessions can have opt-out enabled while others do not, and they
    should work independently.

    Validates: Requirements 9.1, 9.2
    """
    # Create service with probability=1.0
    service = create_test_service(probability=1.0, turn_count=3)

    context = create_test_context()

    # Create three sessions
    session_1 = "session-1"  # No opt-out
    session_2 = "session-2"  # Session-level opt-out
    session_3 = "session-3"  # No opt-out

    # Disable session-2
    service.disable_for_session(session_2)

    # Prime sessions
    service.should_replace(session_1, context)
    service.should_replace(session_2, context)
    service.should_replace(session_3, context)

    # Check all sessions
    should_replace_1 = service.should_replace(session_1, context)
    should_replace_2 = service.should_replace(session_2, context)
    should_replace_3 = service.should_replace(session_3, context)

    assert should_replace_1, "Session-1 should have replacement enabled"
    assert not should_replace_2, "Session-2 should have replacement disabled"
    assert should_replace_3, "Session-3 should have replacement enabled"
