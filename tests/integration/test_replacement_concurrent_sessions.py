"""Integration tests for concurrent session handling with model replacement.

This module tests that multiple sessions can have independent replacement state,
verifying no cross-session interference and proper session cleanup.

Feature: random-model-replacement
Validates: Requirements 5.1, 5.2, 5.3
"""

from __future__ import annotations

import asyncio

import pytest
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.request_context import RequestContext
from src.core.services.backend_registry import BackendRegistry
from src.core.services.model_replacement_service import ModelReplacementService

from tests.utils.fake_clock import FakeClockContext


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


def create_test_context() -> RequestContext:
    """Helper to create a test request context."""
    return RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
    )


@pytest.mark.asyncio
async def test_independent_session_states() -> None:
    """Test that multiple sessions have independent replacement state.

    When multiple sessions are active, each should maintain its own replacement
    state without affecting others.

    Validates: Requirements 5.1, 5.2
    """
    # Create service with 3-turn window
    service = create_test_service(probability=1.0, turn_count=3)

    context = create_test_context()

    # Create three sessions
    session_ids = ["session-1", "session-2", "session-3"]

    # Activate replacement for session-1
    should_replace_1 = service.should_replace(session_ids[0], context)
    assert should_replace_1
    await service.activate_replacement(
        session_ids[0], "original-backend", "original-model"
    )

    # Verify session-1 is active
    state_1 = service.get_state(session_ids[0])
    assert state_1.active
    assert state_1.turns_remaining == 3

    # Verify session-2 and session-3 are not active
    state_2 = service.get_state(session_ids[1])
    state_3 = service.get_state(session_ids[2])
    assert not state_2.active
    assert not state_3.active

    # Activate replacement for session-2
    should_replace_2 = service.should_replace(session_ids[1], context)
    assert should_replace_2
    await service.activate_replacement(
        session_ids[1], "original-backend", "original-model"
    )

    # Verify session-2 is active, session-1 unchanged, session-3 still inactive
    state_1 = service.get_state(session_ids[0])
    state_2 = service.get_state(session_ids[1])
    state_3 = service.get_state(session_ids[2])

    assert state_1.active
    assert state_1.turns_remaining == 3
    assert state_2.active
    assert state_2.turns_remaining == 3
    assert not state_3.active

    # Complete a turn for session-1
    service.complete_turn(session_ids[0])

    # Verify only session-1 was affected
    state_1 = service.get_state(session_ids[0])
    state_2 = service.get_state(session_ids[1])
    state_3 = service.get_state(session_ids[2])

    assert state_1.active
    assert state_1.turns_remaining == 2
    assert state_2.active
    assert state_2.turns_remaining == 3  # Unchanged
    assert not state_3.active


@pytest.mark.asyncio
async def test_no_cross_session_interference() -> None:
    """Test that operations on one session do not affect other sessions.

    Activating, deactivating, or modifying state in one session should have
    no impact on other sessions.

    Validates: Requirements 5.2
    """
    # Create service with 2-turn window
    service = create_test_service(probability=1.0, turn_count=2)

    create_test_context()

    # Create two sessions
    session_a = "session-a"
    session_b = "session-b"

    # Activate replacement for both sessions
    await service.activate_replacement(session_a, "original-backend", "original-model")
    await service.activate_replacement(session_b, "original-backend", "original-model")

    # Verify both are active
    state_a = service.get_state(session_a)
    state_b = service.get_state(session_b)
    assert state_a.active
    assert state_b.active

    # Complete all turns for session-a
    service.complete_turn(session_a)
    service.complete_turn(session_a)

    # Verify session-a is deactivated but session-b is unchanged
    state_a = service.get_state(session_a)
    state_b = service.get_state(session_b)

    assert not state_a.active
    assert state_a.turns_remaining == 0
    assert state_b.active
    assert state_b.turns_remaining == 2

    # Disable replacement for session-a
    service.disable_for_session(session_a)

    # Verify session-b is still active and unaffected
    state_b = service.get_state(session_b)
    assert state_b.active
    assert state_b.turns_remaining == 2


@pytest.mark.asyncio
async def test_session_cleanup() -> None:
    """Test that session state is properly cleaned up.

    When a session ends, its replacement state should be removed from memory.

    Validates: Requirements 5.3
    """
    # Create service
    service = create_test_service(probability=1.0, turn_count=3)

    context = create_test_context()
    session_id = "test-session"

    # Activate replacement
    should_replace = service.should_replace(session_id, context)
    assert should_replace
    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Verify state exists
    state = service.get_state(session_id)
    assert state.active

    # Clean up session
    service.cleanup_session(session_id)

    # Verify state was removed (new state should be created with default values)
    state = service.get_state(session_id)
    assert not state.active
    assert state.turns_remaining == 0


@pytest.mark.asyncio
async def test_concurrent_session_operations() -> None:
    """Test that concurrent operations on different sessions work correctly.

    Multiple sessions should be able to perform operations concurrently without
    race conditions or state corruption.

    Validates: Requirements 5.1, 5.2
    """
    # Create service
    service = create_test_service(probability=1.0, turn_count=5)

    create_test_context()

    # Create multiple sessions
    num_sessions = 10
    session_ids = [f"session-{i}" for i in range(num_sessions)]

    # Activate replacement for all sessions concurrently
    async def activate_session(session_id: str) -> None:
        await service.activate_replacement(
            session_id, "original-backend", "original-model"
        )

    await asyncio.gather(*[activate_session(sid) for sid in session_ids])

    # Verify all sessions are active
    for session_id in session_ids:
        state = service.get_state(session_id)
        assert state.active
        assert state.turns_remaining == 5

    # Complete turns concurrently for different sessions
    async def complete_turns(session_id: str, num_turns: int) -> None:
        async with FakeClockContext() as clock:
            for _ in range(num_turns):
                service.complete_turn(session_id)
                sleep_task = asyncio.create_task(asyncio.sleep(0.001))
                clock.advance(0.001)  # Small delay to simulate real usage
                await sleep_task

    # Complete different numbers of turns for each session
    tasks = [complete_turns(session_ids[i], i % 5 + 1) for i in range(num_sessions)]
    await asyncio.gather(*tasks)

    # Verify each session has the correct state
    for i, session_id in enumerate(session_ids):
        state = service.get_state(session_id)
        expected_remaining = max(0, 5 - (i % 5 + 1))
        assert state.turns_remaining == expected_remaining

        if expected_remaining > 0:
            assert state.active
        else:
            assert not state.active


@pytest.mark.asyncio
async def test_session_isolation_with_different_backends() -> None:
    """Test that sessions can use different original backends independently.

    Each session should be able to have its own original backend:model and
    replacement should work independently for each.

    Validates: Requirements 5.1, 5.2
    """
    # Create service
    service = create_test_service(probability=1.0, turn_count=2)

    create_test_context()

    # Register additional backends
    registry = service._backend_registry
    registry.register_backend("backend-a", lambda: None)
    registry.register_backend("backend-b", lambda: None)

    # Create two sessions with different original backends
    session_1 = "session-1"
    session_2 = "session-2"

    # Activate replacement for session-1 with backend-a
    await service.activate_replacement(session_1, "backend-a", "model-a")

    # Activate replacement for session-2 with backend-b
    await service.activate_replacement(session_2, "backend-b", "model-b")

    # Verify each session has correct original backend stored
    state_1 = service.get_state(session_1)
    state_2 = service.get_state(session_2)

    assert state_1.original_backend == "backend-a"
    assert state_1.original_model == "model-a"
    assert state_2.original_backend == "backend-b"
    assert state_2.original_model == "model-b"

    # Both should use the same replacement backend
    assert state_1.replacement_backend == "replacement-backend"
    assert state_1.replacement_model == "replacement-model"
    assert state_2.replacement_backend == "replacement-backend"
    assert state_2.replacement_model == "replacement-model"


@pytest.mark.asyncio
async def test_cleanup_multiple_sessions() -> None:
    """Test that multiple sessions can be cleaned up independently.

    Cleaning up one session should not affect other sessions.

    Validates: Requirements 5.3
    """
    # Create service
    service = create_test_service(probability=1.0, turn_count=3)

    create_test_context()

    # Create three sessions
    session_ids = ["session-1", "session-2", "session-3"]

    # Activate replacement for all sessions
    for session_id in session_ids:
        await service.activate_replacement(
            session_id, "original-backend", "original-model"
        )

    # Verify all are active
    for session_id in session_ids:
        state = service.get_state(session_id)
        assert state.active

    # Clean up session-2
    service.cleanup_session(session_ids[1])

    # Verify session-2 is cleaned up but others are not
    state_1 = service.get_state(session_ids[0])
    state_2 = service.get_state(session_ids[1])
    state_3 = service.get_state(session_ids[2])

    assert state_1.active  # Still active
    assert not state_2.active  # Cleaned up
    assert state_3.active  # Still active


@pytest.mark.asyncio
async def test_session_state_after_cleanup_and_reactivation() -> None:
    """Test that a session can be reactivated after cleanup.

    After cleaning up a session, it should be possible to activate replacement
    again with fresh state.

    Validates: Requirements 5.3
    """
    # Create service
    service = create_test_service(probability=1.0, turn_count=3)

    create_test_context()
    session_id = "test-session"

    # First activation
    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Complete one turn
    service.complete_turn(session_id)

    # Verify state
    state = service.get_state(session_id)
    assert state.active
    assert state.turns_remaining == 2

    # Clean up session
    service.cleanup_session(session_id)

    # Verify cleanup
    state = service.get_state(session_id)
    assert not state.active
    assert state.turns_remaining == 0

    # Reactivate replacement
    await service.activate_replacement(session_id, "original-backend", "original-model")

    # Verify fresh state
    state = service.get_state(session_id)
    assert state.active
    assert state.turns_remaining == 3  # Reset to full count


@pytest.mark.asyncio
async def test_high_concurrency_session_management() -> None:
    """Test session management under high concurrency.

    The service should handle many concurrent sessions without state corruption
    or race conditions.

    Validates: Requirements 5.1, 5.2
    """
    # Create service
    service = create_test_service(probability=1.0, turn_count=10)

    create_test_context()

    # Create many sessions
    num_sessions = 100
    session_ids = [f"session-{i}" for i in range(num_sessions)]

    # Perform concurrent operations
    async def session_workflow(session_id: str, turns: int) -> None:
        # Activate
        await service.activate_replacement(
            session_id, "original-backend", "original-model"
        )

        # Complete some turns
        for _ in range(turns):
            service.complete_turn(session_id)

        # Check state
        state = service.get_state(session_id)
        expected_remaining = max(0, 10 - turns)
        assert state.turns_remaining == expected_remaining

    # Run workflows concurrently
    tasks = [session_workflow(session_ids[i], i % 10 + 1) for i in range(num_sessions)]
    await asyncio.gather(*tasks)

    # Verify all sessions have correct final state
    for i, session_id in enumerate(session_ids):
        state = service.get_state(session_id)
        expected_remaining = max(0, 10 - (i % 10 + 1))
        assert state.turns_remaining == expected_remaining
