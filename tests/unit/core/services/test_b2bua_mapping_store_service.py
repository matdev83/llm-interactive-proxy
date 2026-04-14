from __future__ import annotations

import pytest
from src.core.services.b2bua_mapping_store_service import (
    B2buaContinuityResolution,
    InMemoryB2buaMappingStore,
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


@pytest.mark.asyncio
async def test_resolve_or_create_reuses_active_mapping() -> None:
    clock = _MutableClock(initial=100.0)
    factory = _sequenced_factory()
    store = InMemoryB2buaMappingStore(
        continuity_ttl_seconds=60,
        sliding_expiration=True,
        max_entries=100,
        time_provider=clock,
    )

    first = await store.resolve_or_create_a_session_id(
        auth_scope_id="token-1",
        client_session_id="client-1",
        create_a_session_id=factory,
    )
    second = await store.resolve_or_create_a_session_id(
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
async def test_resolve_or_create_creates_new_mapping_after_expiration() -> None:
    clock = _MutableClock(initial=0.0)
    factory = _sequenced_factory()
    store = InMemoryB2buaMappingStore(
        continuity_ttl_seconds=10,
        sliding_expiration=True,
        max_entries=100,
        time_provider=clock,
    )

    first = await store.resolve_or_create_a_session_id(
        auth_scope_id="token-1",
        client_session_id="client-1",
        create_a_session_id=factory,
    )
    clock.advance(11)
    second = await store.resolve_or_create_a_session_id(
        auth_scope_id="token-1",
        client_session_id="client-1",
        create_a_session_id=factory,
    )

    assert first.a_session_id == "a-1"
    assert first.reused_existing is False
    assert second.a_session_id == "a-2"
    assert second.reused_existing is False


@pytest.mark.asyncio
async def test_resolve_or_create_applies_sliding_expiration_when_enabled() -> None:
    clock = _MutableClock(initial=0.0)
    factory = _sequenced_factory()
    store = InMemoryB2buaMappingStore(
        continuity_ttl_seconds=10,
        sliding_expiration=True,
        max_entries=100,
        time_provider=clock,
    )

    first = await store.resolve_or_create_a_session_id(
        auth_scope_id="token-1",
        client_session_id="client-1",
        create_a_session_id=factory,
    )
    clock.advance(9)
    touch = await store.resolve_or_create_a_session_id(
        auth_scope_id="token-1",
        client_session_id="client-1",
        create_a_session_id=factory,
    )
    clock.advance(8)
    still_active = await store.resolve_or_create_a_session_id(
        auth_scope_id="token-1",
        client_session_id="client-1",
        create_a_session_id=factory,
    )

    assert first.a_session_id == "a-1"
    assert touch.reused_existing is True
    assert still_active.a_session_id == "a-1"
    assert still_active.reused_existing is True


@pytest.mark.asyncio
async def test_resolve_or_create_enforces_bounded_growth_via_eviction() -> None:
    clock = _MutableClock(initial=0.0)
    factory = _sequenced_factory()
    store = InMemoryB2buaMappingStore(
        continuity_ttl_seconds=60,
        sliding_expiration=True,
        max_entries=2,
        time_provider=clock,
    )

    await store.resolve_or_create_a_session_id(
        auth_scope_id="token-1",
        client_session_id="client-1",
        create_a_session_id=factory,
    )  # a-1
    clock.advance(1)
    await store.resolve_or_create_a_session_id(
        auth_scope_id="token-2",
        client_session_id="client-2",
        create_a_session_id=factory,
    )  # a-2
    clock.advance(1)
    await store.resolve_or_create_a_session_id(
        auth_scope_id="token-3",
        client_session_id="client-3",
        create_a_session_id=factory,
    )  # a-3 (evicts oldest mapping)
    clock.advance(1)
    recreated = await store.resolve_or_create_a_session_id(
        auth_scope_id="token-1",
        client_session_id="client-1",
        create_a_session_id=factory,
    )

    assert recreated.a_session_id == "a-4"
    assert recreated.reused_existing is False


@pytest.mark.asyncio
async def test_resolve_or_create_fails_open_on_internal_store_error() -> None:
    class _BrokenStore(InMemoryB2buaMappingStore):
        async def _resolve_or_create_core(  # type: ignore[override]
            self,
            auth_scope_id: str,
            client_session_id: str,
            create_a_session_id,
        ) -> B2buaContinuityResolution:
            raise RuntimeError("simulated store failure")

    store = _BrokenStore(
        continuity_ttl_seconds=60,
        sliding_expiration=True,
        max_entries=100,
    )
    factory = _sequenced_factory(prefix="fallback-")

    result = await store.resolve_or_create_a_session_id(
        auth_scope_id="token-1",
        client_session_id="client-1",
        create_a_session_id=factory,
    )

    assert result == B2buaContinuityResolution(
        a_session_id="fallback-1",
        reused_existing=False,
        had_store_error=True,
    )


@pytest.mark.asyncio
async def test_try_resolve_echoed_reuses_anon_mapping_for_localhost_scope() -> None:
    store = InMemoryB2buaMappingStore(continuity_ttl_seconds=60)
    first = await store.resolve_or_create_a_session_id(
        auth_scope_id="__b2bua-anon-auth__:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        client_session_id="__b2bua-anon-client__",
        create_a_session_id=lambda: "llm-b2bua-11111111-1111-1111-1111-111111111111",
    )
    assert first.a_session_id == "llm-b2bua-11111111-1111-1111-1111-111111111111"
    hit = await store.try_resolve_echoed_a_session_id(
        a_session_id=first.a_session_id,
        requesting_auth_scope_id="localhost",
    )
    assert hit == B2buaContinuityResolution(
        a_session_id=first.a_session_id,
        reused_existing=True,
        had_store_error=False,
    )


@pytest.mark.asyncio
async def test_try_resolve_echoed_rejects_cross_token_auth() -> None:
    store = InMemoryB2buaMappingStore(continuity_ttl_seconds=60)
    first = await store.resolve_or_create_a_session_id(
        auth_scope_id="token-a",
        client_session_id="client-1",
        create_a_session_id=lambda: "llm-b2bua-22222222-2222-2222-2222-222222222222",
    )
    miss = await store.try_resolve_echoed_a_session_id(
        a_session_id=first.a_session_id,
        requesting_auth_scope_id="token-b",
    )
    assert miss is None
