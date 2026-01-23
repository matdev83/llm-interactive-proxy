"""Tests to ensure the replacement cool-down mechanism works correctly."""

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
    registry.get_registered_backends.return_value = ["original-backend", "replacement-backend"]
    return registry


@pytest.mark.asyncio
async def test_cool_down_is_enforced_after_replacement_cycle(mock_backend_registry):
    """
    Verify that after a replacement cycle finishes, a one-turn cool-down
    is enforced where the dice roll is skipped and the original model is used.
    """
    # 1. Prepare random generator
    mock_random_gen = MagicMock()
    
    # 2. Configure the service with a 1-turn replacement window
    config = ReplacementConfig(
        enabled=True,
        probability=1.0,
        backend_model="replacement-backend:model",
        turn_count=1
    )
    service = ModelReplacementService(config, mock_backend_registry, random_generator=mock_random_gen)
    session_id = "test-cooldown-session"
    context = RequestContext(headers={}, cookies={}, state={}, app_state=None)

    # 3. First request: Should be the guaranteed-original first turn
    mock_random_gen.return_value = 0.1 # Should NOT be used yet
    assert service.should_replace(session_id, context) is False
    mock_random_gen.assert_not_called()

    # 4. Second request: Now it rolls and activates replacement
    assert service.should_replace(session_id, context) is True
    await service.activate_replacement(session_id, "original-backend", "original-model")
    service.complete_turn(session_id)
    
    # At this point, the replacement is deactivated and cool_down_active should be True
    state = service.get_state(session_id)
    assert not state.active
    assert state.cool_down_active

    # 5. Third request: This should be the cool-down turn
    # Now we set the side effect to fail if called
    mock_random_gen.side_effect = Exception("Dice roll performed during cool-down!")
    
    try:
        should_replace = service.should_replace(session_id, context)
        assert should_replace is False, "should_replace should be False during cool-down"
    except Exception:
        pytest.fail("The probability dice roll was performed during the cool-down turn.")
        
    # Verify that the cool-down has been consumed
    assert not service.get_state(session_id).cool_down_active

    # 6. Fourth request: The cool-down is over, so the dice roll should now happen
    mock_random_gen.side_effect = None # Disable the exception
    mock_random_gen.return_value = 0.1 # Ensure dice roll succeeds
    
    assert service.should_replace(session_id, context) is True
    # total calls should be 2 (second request + this fourth request)
    assert mock_random_gen.call_count == 2
