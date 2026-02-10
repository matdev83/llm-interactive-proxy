from __future__ import annotations

from pathlib import Path

import pytest
from src.core.services.b2bua_bleg_allocator_service import (
    B2buaBlegAllocator,
    BlegAllocation,
)
from src.core.services.b2bua_mapping_store_service import (
    InMemoryB2buaMappingStore,
    PersistentB2buaMappingStore,
)
from src.core.services.b2bua_session_id_factory import B2BUASessionIdFactory


class _MutableClock:
    def __init__(self, initial: float = 0.0) -> None:
        self.now = initial

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.mark.asyncio
async def test_allocator_creates_monotonic_b_legs_and_records_attempt_metadata() -> (
    None
):
    clock = _MutableClock(initial=0.0)
    store = InMemoryB2buaMappingStore(
        continuity_ttl_seconds=60,
        sliding_expiration=True,
        max_entries=1_000,
        time_provider=clock,
    )
    a_session_id = "llm-b2bua-12345678-1234-1234-1234-123456789abc"
    await store.resolve_or_create_a_session_id(
        auth_scope_id="token-1",
        client_session_id="client-1",
        create_a_session_id=lambda: a_session_id,
    )
    allocator = B2buaBlegAllocator(
        mapping_store=store,
        session_id_factory=B2BUASessionIdFactory(),
    )

    first = await allocator.allocate(
        a_session_id=a_session_id,
        backend_type="openai",
        effective_model="gpt-4.1",
        reason="primary-attempt",
    )
    second = await allocator.allocate(
        a_session_id=a_session_id,
        backend_type="openrouter",
        effective_model="claude-3.7-sonnet",
        reason="failover-attempt",
    )

    assert first == BlegAllocation(
        b_session_id="llm-b2bua-b-12345678-1234-1234-1234-123456789abc-1",
        seq=1,
    )
    assert second == BlegAllocation(
        b_session_id="llm-b2bua-b-12345678-1234-1234-1234-123456789abc-2",
        seq=2,
    )

    attempts = await store.get_attempt_records(a_session_id)
    assert len(attempts) == 2
    assert attempts[0].backend_type == "openai"
    assert attempts[0].effective_model == "gpt-4.1"
    assert attempts[0].reason == "primary-attempt"
    assert attempts[1].backend_type == "openrouter"
    assert attempts[1].effective_model == "claude-3.7-sonnet"
    assert attempts[1].reason == "failover-attempt"


@pytest.mark.asyncio
async def test_allocator_persistent_mode_preserves_seq_and_attempts_across_restart(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "b2bua-bleg-allocator.sqlite3"
    clock = _MutableClock(initial=0.0)
    a_session_id = "llm-b2bua-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

    first_store = PersistentB2buaMappingStore(
        database_path=db_path,
        continuity_ttl_seconds=60,
        sliding_expiration=True,
        max_entries=1_000,
        time_provider=clock,
    )
    await first_store.resolve_or_create_a_session_id(
        auth_scope_id="token-1",
        client_session_id="client-1",
        create_a_session_id=lambda: a_session_id,
    )
    first_allocator = B2buaBlegAllocator(
        mapping_store=first_store,
        session_id_factory=B2BUASessionIdFactory(),
    )
    first = await first_allocator.allocate(
        a_session_id=a_session_id,
        backend_type="openai",
        effective_model="gpt-4.1",
        reason="initial-attempt",
    )

    second_store = PersistentB2buaMappingStore(
        database_path=db_path,
        continuity_ttl_seconds=60,
        sliding_expiration=True,
        max_entries=1_000,
        time_provider=clock,
    )
    second_allocator = B2buaBlegAllocator(
        mapping_store=second_store,
        session_id_factory=B2BUASessionIdFactory(),
    )
    second = await second_allocator.allocate(
        a_session_id=a_session_id,
        backend_type="openrouter",
        effective_model="claude-3.7-sonnet",
        reason="retry-attempt",
    )

    assert first.seq == 1
    assert second.seq == 2
    attempts = await second_store.get_attempt_records(a_session_id)
    assert [attempt.seq for attempt in attempts] == [1, 2]


@pytest.mark.asyncio
async def test_attempt_records_are_retained_until_mapping_expiration() -> None:
    clock = _MutableClock(initial=0.0)
    store = InMemoryB2buaMappingStore(
        continuity_ttl_seconds=10,
        sliding_expiration=True,
        max_entries=1_000,
        time_provider=clock,
    )
    allocator = B2buaBlegAllocator(
        mapping_store=store,
        session_id_factory=B2BUASessionIdFactory(),
    )
    a_session_id = "llm-b2bua-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

    await store.resolve_or_create_a_session_id(
        auth_scope_id="token-1",
        client_session_id="client-1",
        create_a_session_id=lambda: a_session_id,
    )
    await allocator.allocate(
        a_session_id=a_session_id,
        backend_type="openai",
        effective_model="gpt-4.1",
        reason="failed-attempt",
    )

    before_expiry = await store.get_attempt_records(a_session_id)
    assert len(before_expiry) == 1

    clock.advance(11)
    await store.resolve_or_create_a_session_id(
        auth_scope_id="token-2",
        client_session_id="client-2",
        create_a_session_id=lambda: "llm-b2bua-cccccccc-cccc-cccc-cccc-cccccccccccc",
    )
    after_expiry = await store.get_attempt_records(a_session_id)
    assert after_expiry == []
