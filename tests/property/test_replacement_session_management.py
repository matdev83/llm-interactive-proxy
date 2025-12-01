"""Property-based tests for replacement session management.

Feature: random-model-replacement
Properties: 18, 19, 32, 35
Validates: Requirements 5.1, 5.2, 5.3, 9.2, 9.5
"""

from __future__ import annotations

from hypothesis import HealthCheck, given
from hypothesis import strategies as st
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.request_context import RequestContext
from src.core.services.backend_registry import BackendRegistry
from src.core.services.model_replacement_service import ModelReplacementService
from tests.utils.hypothesis_config import property_test_settings


def create_test_service() -> ModelReplacementService:
    """Helper to create a test replacement service."""
    registry = BackendRegistry()
    registry.register_backend("test-backend", lambda: None)

    config = ReplacementConfig(
        enabled=True,
        probability=0.5,
        backend_model="test-backend:test-model",
        turn_count=5,
    )

    return ModelReplacementService(config, registry)


@given(
    session_id_1=st.text(min_size=1, max_size=10).filter(lambda x: x.isalnum()),
    session_id_2=st.text(min_size=1, max_size=10).filter(lambda x: x.isalnum()),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
def test_property_18_independent_session_states(
    session_id_1: str,
    session_id_2: str,
) -> None:
    """
    Property 18: Independent session states.

    Replacement state for one session must not affect other sessions.

    Validates: Requirements 5.1, 5.2
    """
    if session_id_1 == session_id_2:
        return

    service = create_test_service()

    # Activate session 1
    import asyncio

    asyncio.run(service.activate_replacement(session_id_1, "orig", "mod"))

    # Verify session 2 is inactive
    state2 = service.get_state(session_id_2)
    assert state2.active is False
    assert state2.turns_remaining == 0

    # Verify session 1 is active
    state1 = service.get_state(session_id_1)
    assert state1.active is True


@given(
    session_id=st.text(min_size=1, max_size=10).filter(lambda x: x.isalnum()),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
def test_property_19_session_cleanup(
    session_id: str,
) -> None:
    """
    Property 19: Session cleanup.

    When a session is cleaned up, its state must be removed.

    Validates: Requirements 5.3
    """
    service = create_test_service()

    # Activate session
    import asyncio

    asyncio.run(service.activate_replacement(session_id, "orig", "mod"))

    # Verify state exists
    # Accessing private member for verification as get_state creates new state if missing
    assert session_id in service._session_states

    # Cleanup
    service.cleanup_session(session_id)

    # Verify state removed
    assert session_id not in service._session_states


@given(
    session_id=st.text(min_size=1, max_size=10).filter(lambda x: x.isalnum()),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
def test_property_32_35_session_disable_and_deactivation(
    session_id: str,
) -> None:
    """
    Properties 32 & 35: Session-level opt-out and immediate deactivation.

    Validates: Requirements 9.2, 9.5
    """
    service = create_test_service()
    context = RequestContext(headers={}, cookies={}, state=None, app_state=None)

    # Activate session
    import asyncio

    asyncio.run(service.activate_replacement(session_id, "orig", "mod"))
    assert service.get_state(session_id).active is True

    # Disable session
    service.disable_for_session(session_id)

    # Verify immediate deactivation (Property 35)
    assert service.get_state(session_id).active is False

    # Verify opt-out (Property 32)
    # Even with probability 1.0 (simulated by mocking random if needed, but here we check should_replace logic)
    # We can't easily force probability 1.0 here without recreating service, but we can check if it returns False
    # knowing that normally it would check probability.
    # But more importantly, we can check if it's in disabled sessions
    assert session_id in service._disabled_sessions

    # should_replace should return False for disabled session
    assert service.should_replace(session_id, context) is False
