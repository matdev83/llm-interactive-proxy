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
    naive_last_active = datetime.utcnow() - timedelta(minutes=5)
    session = Session(session_id="session-naive", last_active_at=naive_last_active)
    await repo.add(session)

    removed_count = await repo.cleanup_expired(max_age_seconds=60)

    assert removed_count == 1
