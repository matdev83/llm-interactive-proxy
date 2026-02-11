from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from src.core.services.b2bua_mapping_store_service import (
    B2buaContinuityResolution,
    PersistentB2buaMappingStore,
)


class _MutableClock:
    def __init__(self, initial: float = 0.0) -> None:
        self.now = initial

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _sequenced_factory(prefix: str = "a-"):
    counter = 0

    def _factory() -> str:
        nonlocal counter
        counter += 1
        return f"{prefix}{counter}"

    return _factory


def _make_store(path: Path, *, clock: _MutableClock) -> PersistentB2buaMappingStore:
    return PersistentB2buaMappingStore(
        database_path=path,
        continuity_ttl_seconds=10,
        sliding_expiration=True,
        max_entries=1_000,
        time_provider=clock,
    )


@pytest.mark.asyncio
async def test_persistent_store_reuses_mapping_across_instances(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "b2bua-continuity.sqlite3"
    clock = _MutableClock(initial=100.0)
    factory = _sequenced_factory()

    first_store = _make_store(db_path, clock=clock)
    first = await first_store.resolve_or_create_a_session_id(
        auth_scope_id="token-1",
        client_session_id="client-1",
        create_a_session_id=factory,
    )

    second_store = _make_store(db_path, clock=clock)
    second = await second_store.resolve_or_create_a_session_id(
        auth_scope_id="token-1",
        client_session_id="client-1",
        create_a_session_id=factory,
    )

    assert first == B2buaContinuityResolution(
        a_session_id="a-1",
        reused_existing=False,
        had_store_error=False,
    )
    assert second == B2buaContinuityResolution(
        a_session_id="a-1",
        reused_existing=True,
        had_store_error=False,
    )


@pytest.mark.asyncio
async def test_persistent_store_persists_last_b_seq_across_instances(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "b2bua-seq.sqlite3"
    clock = _MutableClock(initial=0.0)
    factory = _sequenced_factory(prefix="llm-b2bua-")

    first_store = _make_store(db_path, clock=clock)
    resolution = await first_store.resolve_or_create_a_session_id(
        auth_scope_id="token-1",
        client_session_id="client-1",
        create_a_session_id=factory,
    )

    seq_1 = await first_store.allocate_next_b_seq(resolution.a_session_id)
    seq_2 = await first_store.allocate_next_b_seq(resolution.a_session_id)

    second_store = _make_store(db_path, clock=clock)
    seq_3 = await second_store.allocate_next_b_seq(resolution.a_session_id)

    assert (seq_1, seq_2, seq_3) == (1, 2, 3)


@pytest.mark.asyncio
async def test_persistent_store_allocates_unique_sequences_under_concurrency(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "b2bua-concurrency.sqlite3"
    clock = _MutableClock(initial=0.0)
    store = _make_store(db_path, clock=clock)
    factory = _sequenced_factory(prefix="llm-b2bua-")

    resolution = await store.resolve_or_create_a_session_id(
        auth_scope_id="token-1",
        client_session_id="client-1",
        create_a_session_id=factory,
    )

    async def _allocate_once() -> int:
        return await store.allocate_next_b_seq(resolution.a_session_id)

    results = await asyncio.gather(*[_allocate_once() for _ in range(20)])

    assert sorted(results) == list(range(1, 21))
    assert len(set(results)) == 20


@pytest.mark.asyncio
async def test_persistent_store_respects_expiration_across_restart(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "b2bua-expiration.sqlite3"
    clock = _MutableClock(initial=0.0)
    factory = _sequenced_factory()

    first_store = _make_store(db_path, clock=clock)
    first = await first_store.resolve_or_create_a_session_id(
        auth_scope_id="token-1",
        client_session_id="client-1",
        create_a_session_id=factory,
    )

    clock.advance(11)
    second_store = _make_store(db_path, clock=clock)
    second = await second_store.resolve_or_create_a_session_id(
        auth_scope_id="token-1",
        client_session_id="client-1",
        create_a_session_id=factory,
    )

    assert first.a_session_id == "a-1"
    assert second.a_session_id == "a-2"
    assert second.reused_existing is False
