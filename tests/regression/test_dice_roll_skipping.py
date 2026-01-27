"""Tests to ensure probability checks are correctly skipped during active replacements."""

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
async def test_dice_roll_is_skipped_during_active_replacement(mock_backend_registry):
    """
    Verify that the probability "dice roll" is NOT performed when a replacement
    is already active for a session.
    """
    # 1. Mock the random generator to raise an exception if called
    mock_random_gen = MagicMock(side_effect=Exception("Dice roll was performed!"))

    # 2. Configure the service
    config = ReplacementConfig(
        enabled=True,
        probability=1.0,
        backend_model="replacement-backend:model",
        turn_count=3,
    )

    service = ModelReplacementService(
        config, mock_backend_registry, random_generator=mock_random_gen
    )
    session_id = "test-session-dice-roll"

    # 3. First request: Guaranteed original (skip dice roll)
    # This should return False without calling the generator
    assert (
        service.should_replace(
            session_id, RequestContext(headers={}, cookies={}, state={}, app_state=None)
        )
        is False
    )
    mock_random_gen.assert_not_called()

    # 4. Manually activate the state to simulate a previous activation (for the second request)
    state = service.get_state(session_id)
    state.activate(3, "original-backend", "model", "replacement-backend", "model")

    # 5. Call should_replace again
    # Because state.active is True, the function should return True immediately
    # without ever calling the mock_random_gen.
    try:
        should_replace = service.should_replace(
            session_id, RequestContext(headers={}, cookies={}, state={}, app_state=None)
        )
        assert should_replace is True
    except Exception:
        pytest.fail(
            "The probability dice roll was performed during an active replacement window."
        )

    # 6. Verify the mock was never called
    mock_random_gen.assert_not_called()

    # 7. Deactivate and verify the dice roll IS performed now
    service.complete_turn(session_id)  # turn 1
    service.complete_turn(session_id)  # turn 2
    service.complete_turn(session_id)  # turn 3 -> deactivates

    # Consume cool-down turn
    assert (
        service.should_replace(
            session_id, RequestContext(headers={}, cookies={}, state={}, app_state=None)
        )
        is False
    )

    assert not service.get_state(session_id).active
    assert not service.get_state(session_id).cool_down_active

    # Now that it's inactive and cool-down is over, the dice roll SHOULD happen.
    mock_random_gen.side_effect = None
    mock_random_gen.return_value = 0.1  # Ensure it triggers

    should_replace_after = service.should_replace(
        session_id, RequestContext(headers={}, cookies={}, state={}, app_state=None)
    )
    assert should_replace_after is True
    mock_random_gen.assert_called_once()
