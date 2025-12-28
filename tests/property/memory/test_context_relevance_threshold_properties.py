"""Property-based tests for context relevance thresholding.

Feature: proxy-mem
Property: 19
Validates: Requirements 11.8 - Context relevance thresholding
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import cast

import pytest
from hypothesis import HealthCheck, given
from hypothesis import strategies as st
from src.core.memory.config import MemoryConfiguration
from src.core.memory.context_injector import ContextInjector
from src.core.memory.models import SessionSummary
from src.core.memory.repository import IMemoryRepository
from tests.utils.hypothesis_config import property_test_settings


class _StubRepository:
    def __init__(self, summary: SessionSummary) -> None:
        self._summary = summary

    async def get_recent_sessions(
        self, *args: object, **kwargs: object
    ) -> list[SessionSummary]:
        return [self._summary]


def _build_summary(title: str, scope: str) -> SessionSummary:
    old_time = datetime.now(timezone.utc) - timedelta(days=30)
    return SessionSummary(
        id="summary-1",
        user_id="user-1",
        session_id="sess-1",
        session_start=old_time,
        backend_model="backend:model",
        title=title,
        scope=scope,
        completion_status="completed",
        full_analysis="<session_summary></session_summary>",
        summary_version="v1",
        created_at=old_time,
    )


@given(prompt=st.text(min_size=1, max_size=40))
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
@pytest.mark.asyncio
async def test_property_19_threshold_blocks_irrelevant_context(prompt: str) -> None:
    """Summaries below threshold should not be injected."""
    summary = _build_summary(title="alpha beta", scope="gamma delta")
    repo = _StubRepository(summary)
    config = MemoryConfiguration(
        max_sessions_to_consider=1,
        context_relevance_threshold=1.0,
    )
    injector = ContextInjector(
        config=config,
        repository=cast(IMemoryRepository, repo),
    )

    context = await injector.get_context_for_session(
        user_id="user-1",
        current_prompt=f"zzz {prompt} zzz",
    )

    assert context is None
