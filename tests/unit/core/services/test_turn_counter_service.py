from __future__ import annotations

import pytest
from src.core.domain.configuration.assessment_config import AssessmentConfig
from src.core.repositories.assessment_repository import InMemoryAssessmentRepository
from src.core.services.turn_counter_service import TurnCounterService


@pytest.fixture
def turn_counter() -> TurnCounterService:
    repository = InMemoryAssessmentRepository()
    config = AssessmentConfig()
    return TurnCounterService(repository, config)


@pytest.mark.asyncio
async def test_increment_turn_requires_session_id(
    turn_counter: TurnCounterService,
) -> None:
    with pytest.raises(ValueError):
        turn_counter.increment_turn("")


def test_should_trigger_requires_session(turn_counter: TurnCounterService) -> None:
    with pytest.raises(ValueError):
        turn_counter.should_trigger_assessment("")
