from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.core.domain.session import Session
from src.core.repositories.in_memory_session_repository import (
    InMemorySessionRepository,
)


@pytest.mark.asyncio
async def test_cleanup_expired_handles_naive_last_active_at() -> None:
    repo = InMemorySessionRepository()
    session = Session("session-naive")
    session.last_active_at = datetime.utcnow() - timedelta(minutes=10)

    await repo.add(session)

    deleted_count = await repo.cleanup_expired(max_age_seconds=60)

    assert deleted_count == 1
    assert await repo.get_by_id(session.id) is None
