from __future__ import annotations

from uuid import UUID

import pytest
from src.core.config.app_config import AppConfig
from src.core.config.models.access_mode import AccessMode, AccessModeConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.request_context import RequestContext
from src.core.services.auth_scope_resolver_service import DefaultAuthScopeResolver
from src.core.services.b2bua_mapping_store_service import InMemoryB2buaMappingStore
from src.core.services.b2bua_session_id_factory import B2BUASessionIdFactory
from src.core.services.b2bua_session_resolver_service import B2BUASessionResolver
from src.core.services.client_session_id_extractor_service import (
    DefaultClientSessionIdExtractor,
)


def _message_request() -> CanonicalChatRequest:
    return CanonicalChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="hello")],
    )


def _context(
    *,
    headers: dict[str, str] | None = None,
    state: dict[str, object] | None = None,
    request_id: str | None = None,
) -> RequestContext:
    return RequestContext(
        headers=headers or {},
        cookies={},
        state=state or {},
        app_state=None,
        request_id=request_id,
        domain_request=_message_request(),
    )


@pytest.mark.asyncio
async def test_resolver_assigns_new_a_leg_when_client_session_id_missing() -> None:
    config = AppConfig()
    resolver = B2BUASessionResolver(
        client_session_extractor=DefaultClientSessionIdExtractor(config=config),
        auth_scope_resolver=DefaultAuthScopeResolver(config=config),
        mapping_store=InMemoryB2buaMappingStore(continuity_ttl_seconds=60),
        session_id_factory=B2BUASessionIdFactory(
            uuid_factory=iter(
                [
                    UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                    UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
                ]
            ).__next__
        ),
    )

    first_context = _context(state={"auth_scope_id": "token-1"})
    second_context = _context(state={"auth_scope_id": "token-1"})

    first = await resolver.resolve_session_id(first_context)
    second = await resolver.resolve_session_id(second_context)

    assert first == "llm-b2bua-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert second == "llm-b2bua-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert first != second


@pytest.mark.asyncio
async def test_resolver_bootstraps_a_leg_mapping_when_continuity_keys_missing() -> None:
    config = AppConfig()
    mapping_store = InMemoryB2buaMappingStore(continuity_ttl_seconds=60)
    resolver = B2BUASessionResolver(
        client_session_extractor=DefaultClientSessionIdExtractor(config=config),
        auth_scope_resolver=DefaultAuthScopeResolver(config=config),
        mapping_store=mapping_store,
        session_id_factory=B2BUASessionIdFactory(
            uuid_factory=lambda: UUID("12345678-1234-1234-1234-123456789abc")
        ),
    )

    context = _context(state={"auth_scope_id": "token-1"})
    a_session_id = await resolver.resolve_session_id(context)
    first_b_seq = await mapping_store.allocate_next_b_seq(a_session_id)

    assert a_session_id == "llm-b2bua-12345678-1234-1234-1234-123456789abc"
    assert first_b_seq == 1


@pytest.mark.asyncio
async def test_resolver_reuses_mapping_with_same_auth_scope_and_client_session() -> (
    None
):
    config = AppConfig()
    resolver = B2BUASessionResolver(
        client_session_extractor=DefaultClientSessionIdExtractor(config=config),
        auth_scope_resolver=DefaultAuthScopeResolver(config=config),
        mapping_store=InMemoryB2buaMappingStore(continuity_ttl_seconds=60),
        session_id_factory=B2BUASessionIdFactory(
            uuid_factory=iter(
                [
                    UUID("11111111-1111-1111-1111-111111111111"),
                    UUID("22222222-2222-2222-2222-222222222222"),
                ]
            ).__next__
        ),
    )

    first_context = _context(
        headers={"x-session-id": "client-1"},
        state={"auth_scope_id": "token-1"},
    )
    second_context = _context(
        headers={"x-session-id": "client-1"},
        state={"auth_scope_id": "token-1"},
    )

    first = await resolver.resolve_session_id(first_context)
    second = await resolver.resolve_session_id(second_context)

    assert first == "llm-b2bua-11111111-1111-1111-1111-111111111111"
    assert second == first


@pytest.mark.asyncio
async def test_resolver_does_not_reuse_mapping_across_auth_scopes() -> None:
    config = AppConfig()
    resolver = B2BUASessionResolver(
        client_session_extractor=DefaultClientSessionIdExtractor(config=config),
        auth_scope_resolver=DefaultAuthScopeResolver(config=config),
        mapping_store=InMemoryB2buaMappingStore(continuity_ttl_seconds=60),
        session_id_factory=B2BUASessionIdFactory(
            uuid_factory=iter(
                [
                    UUID("33333333-3333-3333-3333-333333333333"),
                    UUID("44444444-4444-4444-4444-444444444444"),
                ]
            ).__next__
        ),
    )

    token_a_context = _context(
        headers={"x-session-id": "client-1"},
        state={"auth_scope_id": "token-a"},
    )
    token_b_context = _context(
        headers={"x-session-id": "client-1"},
        state={"auth_scope_id": "token-b"},
    )

    first = await resolver.resolve_session_id(token_a_context)
    second = await resolver.resolve_session_id(token_b_context)

    assert first == "llm-b2bua-33333333-3333-3333-3333-333333333333"
    assert second == "llm-b2bua-44444444-4444-4444-4444-444444444444"


@pytest.mark.asyncio
async def test_resolver_sets_canonical_session_and_b2bua_identity_on_context() -> None:
    config = AppConfig()
    resolver = B2BUASessionResolver(
        client_session_extractor=DefaultClientSessionIdExtractor(config=config),
        auth_scope_resolver=DefaultAuthScopeResolver(config=config),
        mapping_store=InMemoryB2buaMappingStore(continuity_ttl_seconds=60),
        session_id_factory=B2BUASessionIdFactory(
            uuid_factory=lambda: UUID("55555555-5555-5555-5555-555555555555")
        ),
    )
    context = _context(
        headers={"x-session-id": "client-1"},
        state={"auth_scope_id": "token-1"},
        request_id="req-123",
    )

    resolved = await resolver.resolve_session_id(context)

    assert resolved == "llm-b2bua-55555555-5555-5555-5555-555555555555"
    assert context.session_id == resolved
    assert context.b2bua_identity is not None
    assert context.b2bua_identity.a_session_id == resolved
    assert context.b2bua_identity.client_session_id == "client-1"
    assert context.b2bua_identity.auth_scope_id == "token-1"
    assert context.b2bua_identity.b_session_id is None
    assert context.b2bua_identity.b_seq is None
    assert "req-123" not in resolved


@pytest.mark.asyncio
async def test_resolver_does_not_reuse_when_auth_scope_missing_outside_localhost() -> (
    None
):
    config = AppConfig(
        host="0.0.0.0",
        access_mode=AccessModeConfig(mode=AccessMode.MULTI_USER),
    )
    resolver = B2BUASessionResolver(
        client_session_extractor=DefaultClientSessionIdExtractor(config=config),
        auth_scope_resolver=DefaultAuthScopeResolver(config=config),
        mapping_store=InMemoryB2buaMappingStore(continuity_ttl_seconds=60),
        session_id_factory=B2BUASessionIdFactory(
            uuid_factory=iter(
                [
                    UUID("66666666-6666-6666-6666-666666666666"),
                    UUID("77777777-7777-7777-7777-777777777777"),
                ]
            ).__next__
        ),
    )

    first_context = _context(headers={"x-session-id": "client-1"}, state={})
    second_context = _context(headers={"x-session-id": "client-1"}, state={})

    first = await resolver.resolve_session_id(first_context)
    second = await resolver.resolve_session_id(second_context)

    assert first == "llm-b2bua-66666666-6666-6666-6666-666666666666"
    assert second == "llm-b2bua-77777777-7777-7777-7777-777777777777"


@pytest.mark.asyncio
async def test_resolver_reuses_a_leg_when_client_echoes_prior_session_header() -> None:
    config = AppConfig(
        host="127.0.0.1",
        access_mode=AccessModeConfig(mode=AccessMode.SINGLE_USER),
    )
    fixed = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    spare = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    resolver = B2BUASessionResolver(
        client_session_extractor=DefaultClientSessionIdExtractor(config=config),
        auth_scope_resolver=DefaultAuthScopeResolver(config=config),
        mapping_store=InMemoryB2buaMappingStore(continuity_ttl_seconds=60),
        session_id_factory=B2BUASessionIdFactory(
            uuid_factory=iter([fixed, spare]).__next__
        ),
    )

    first_context = _context(headers={})
    first_id = await resolver.resolve_session_id(first_context)
    assert first_id == "llm-b2bua-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

    second_context = _context(headers={"x-b2bua-session-id": first_id})
    second_id = await resolver.resolve_session_id(second_context)
    assert second_id == first_id


def _config_with_heuristic_inference() -> AppConfig:
    b2bua = AppConfig().session.b2bua.model_copy(
        update={"enable_unsafe_heuristic_session_inference": True}
    )
    session = AppConfig().session.model_copy(update={"b2bua": b2bua})
    return AppConfig().model_copy(update={"session": session})


@pytest.mark.asyncio
async def test_heuristic_inference_derives_client_id_from_user_message() -> None:
    config = _config_with_heuristic_inference()
    resolver = B2BUASessionResolver(
        client_session_extractor=DefaultClientSessionIdExtractor(config=config),
        auth_scope_resolver=DefaultAuthScopeResolver(config=config),
        mapping_store=InMemoryB2buaMappingStore(continuity_ttl_seconds=60),
        session_id_factory=B2BUASessionIdFactory(
            uuid_factory=lambda: UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        ),
        config=config,
    )

    context = _context(
        state={"auth_scope_id": "token-1"},
    )

    resolved = await resolver.resolve_session_id(context)

    assert resolved == "llm-b2bua-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert context.b2bua_identity is not None
    assert context.b2bua_identity.client_session_id is not None
    assert context.b2bua_identity.client_session_id.startswith("b2bua-fallback:")
    assert context.b2bua_identity.auth_scope_id == "token-1"


@pytest.mark.asyncio
async def test_heuristic_inference_reuses_mapping_with_same_auth_scope_and_message() -> (
    None
):
    config = _config_with_heuristic_inference()
    resolver = B2BUASessionResolver(
        client_session_extractor=DefaultClientSessionIdExtractor(config=config),
        auth_scope_resolver=DefaultAuthScopeResolver(config=config),
        mapping_store=InMemoryB2buaMappingStore(continuity_ttl_seconds=60),
        session_id_factory=B2BUASessionIdFactory(
            uuid_factory=iter(
                [
                    UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                    UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
                ]
            ).__next__
        ),
        config=config,
    )

    first_context = _context(state={"auth_scope_id": "token-1"})
    second_context = _context(state={"auth_scope_id": "token-1"})

    first = await resolver.resolve_session_id(first_context)
    second = await resolver.resolve_session_id(second_context)

    assert first == "llm-b2bua-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert second == first
    assert first_context.b2bua_identity is not None
    assert second_context.b2bua_identity is not None
    assert (
        first_context.b2bua_identity.client_session_id
        == second_context.b2bua_identity.client_session_id
    )


@pytest.mark.asyncio
async def test_heuristic_inference_falls_back_to_agent_host_when_no_user_message() -> (
    None
):
    config = _config_with_heuristic_inference()
    resolver = B2BUASessionResolver(
        client_session_extractor=DefaultClientSessionIdExtractor(config=config),
        auth_scope_resolver=DefaultAuthScopeResolver(config=config),
        mapping_store=InMemoryB2buaMappingStore(continuity_ttl_seconds=60),
        session_id_factory=B2BUASessionIdFactory(
            uuid_factory=lambda: UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        ),
        config=config,
    )

    context = _context(
        state={"auth_scope_id": "token-1"},
    )
    context.domain_request = CanonicalChatRequest(
        model="test-model",
        messages=[ChatMessage(role="system", content="You are a helpful assistant")],
    )
    context.agent = "test-agent"
    context.client_host = "192.168.1.1"

    resolved = await resolver.resolve_session_id(context)

    assert resolved == "llm-b2bua-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert context.b2bua_identity is not None
    assert context.b2bua_identity.client_session_id is not None
    assert context.b2bua_identity.client_session_id.startswith("b2bua-fallback:")


@pytest.mark.asyncio
async def test_heuristic_inference_does_not_crash_on_exception() -> None:
    config = _config_with_heuristic_inference()
    resolver = B2BUASessionResolver(
        client_session_extractor=DefaultClientSessionIdExtractor(config=config),
        auth_scope_resolver=DefaultAuthScopeResolver(config=config),
        mapping_store=InMemoryB2buaMappingStore(continuity_ttl_seconds=60),
        session_id_factory=B2BUASessionIdFactory(
            uuid_factory=lambda: UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        ),
        config=config,
    )

    context = _context(
        state={"auth_scope_id": "token-1"},
    )
    context.domain_request = None

    resolved = await resolver.resolve_session_id(context)

    assert resolved == "llm-b2bua-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert context.b2bua_identity is not None
    assert context.b2bua_identity.auth_scope_id == "token-1"


@pytest.mark.asyncio
async def test_heuristic_inference_disabled_creates_new_a_leg() -> None:
    config = AppConfig()
    resolver = B2BUASessionResolver(
        client_session_extractor=DefaultClientSessionIdExtractor(config=config),
        auth_scope_resolver=DefaultAuthScopeResolver(config=config),
        mapping_store=InMemoryB2buaMappingStore(continuity_ttl_seconds=60),
        session_id_factory=B2BUASessionIdFactory(
            uuid_factory=iter(
                [
                    UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                    UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
                ]
            ).__next__
        ),
    )

    first_context = _context(state={"auth_scope_id": "token-1"})
    second_context = _context(state={"auth_scope_id": "token-1"})

    first = await resolver.resolve_session_id(first_context)
    second = await resolver.resolve_session_id(second_context)

    assert first == "llm-b2bua-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert second == "llm-b2bua-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert first != second
