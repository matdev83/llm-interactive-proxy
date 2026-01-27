"""Behavioral tests for the ModelReplacementService."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.request_context import RequestContext
from src.core.services.model_replacement_service import ModelReplacementService


@pytest.fixture
def mock_backend_registry():
    """Fixture for a mock BackendRegistry."""
    registry = MagicMock()
    registry.get_registered_backends.return_value = [
        "original-backend",
        "replacement-backend",
    ]
    return registry


@pytest.mark.asyncio
async def test_replacement_cycle_respects_turn_count(mock_backend_registry):
    """
    Test that the replacement is active for the configured number of turns
    and then deactivates automatically.
    """
    # 1. Configure the service
    config = ReplacementConfig(
        enabled=True,
        probability=1.0,  # Ensure it always triggers
        backend_model="replacement-backend:model",
        turn_count=3,
    )

    service = ModelReplacementService(config, mock_backend_registry)
    session_id = "test-session-123"

    # 2. First request: Guaranteed original
    assert (
        service.should_replace(
            session_id, RequestContext(headers={}, cookies={}, state={}, app_state=None)
        )
        is False
    )

    # 3. Second request: Activate replacement
    # The second `should_replace` call will be True due to probability=1.0
    assert service.should_replace(
        session_id, RequestContext(headers={}, cookies={}, state={}, app_state=None)
    )
    await service.activate_replacement(session_id, "original-backend", "original-model")

    # 4. Simulate the turns

    # Turn 1
    assert service.should_replace(
        session_id, RequestContext(headers={}, cookies={}, state={}, app_state=None)
    )
    backend, model = service.get_effective_backend_model(
        session_id, "original", "model"
    )
    assert backend == "replacement-backend"
    service.complete_turn(session_id)

    # Turn 2
    assert service.should_replace(
        session_id, RequestContext(headers={}, cookies={}, state={}, app_state=None)
    )
    backend, model = service.get_effective_backend_model(
        session_id, "original", "model"
    )
    assert backend == "replacement-backend"
    service.complete_turn(session_id)

    # Turn 3
    assert service.should_replace(
        session_id, RequestContext(headers={}, cookies={}, state={}, app_state=None)
    )
    backend, model = service.get_effective_backend_model(
        session_id, "original", "model"
    )
    assert backend == "replacement-backend"
    service.complete_turn(session_id)  # After this, it should deactivate

    # 5. Verify deactivation

    # The replacement should no longer be active
    assert not service.get_state(session_id).active

    # The next `should_replace` call will re-evaluate probability (and re-activate in this test)
    # but for a different test, we could set probability to 0 to check it stays off.
    # For now, we're just checking that the 3-turn cycle completed.

    # Let's verify the backend falls back to original
    # We need to manually set the state to inactive as should_replace will re-activate
    state = service.get_state(session_id)
    state.deactivate()

    backend, model = service.get_effective_backend_model(
        session_id, "original-backend", "original-model"
    )
    assert backend == "original-backend"
    assert model == "original-model"
