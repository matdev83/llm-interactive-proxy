from __future__ import annotations

import pytest
from src.core.repositories.assessment_repository import InMemoryAssessmentRepository


def test_get_session_state_rejects_empty_session_id() -> None:
    repository = InMemoryAssessmentRepository()
    with pytest.raises(ValueError):
        repository.get_session_state("")


def test_update_and_cleanup_are_thread_safe() -> None:
    repository = InMemoryAssessmentRepository()
    state = repository.get_session_state("session-1")
    repository.update_session_state(state)
    assert "session-1" in repository.get_all_session_ids()
    repository.cleanup_expired_sessions(max_age_seconds=0)
