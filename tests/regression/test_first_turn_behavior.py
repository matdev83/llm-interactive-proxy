"""Tests to ensure the replacement dice roll is skipped on the first turn of a session."""

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
async def test_dice_roll_is_skipped_on_first_turn(mock_backend_registry):
    """
    Verify that the very first request of a new session always uses the 
    original model and skips the probability dice roll.
    """
    # 1. Prepare random generator to fail if called
    mock_random_gen = MagicMock(side_effect=Exception("Dice roll performed on first turn!"))
    
    # 2. Configure the service
    config = ReplacementConfig(
        enabled=True,
        probability=1.0, # Would normally always trigger
        backend_model="replacement-backend:model",
        turn_count=3
    )
    service = ModelReplacementService(config, mock_backend_registry, random_generator=mock_random_gen)
    session_id = "brand-new-session"
    context = RequestContext(headers={}, cookies={}, state={}, app_state=None)

    # 3. First request: Should return False and NOT call random_generator
    try:
        should_replace = service.should_replace(session_id, context)
        assert should_replace is False, "First turn should never trigger replacement"
    except Exception:
        pytest.fail("The probability dice roll was performed on the very first turn.")
        
    mock_random_gen.assert_not_called()
    
    # 4. Second request: Now it SHOULD roll the dice
    mock_random_gen.side_effect = None
    mock_random_gen.return_value = 0.1 # Trigger
    
    assert service.should_replace(session_id, context) is True
    mock_random_gen.assert_called_once()
