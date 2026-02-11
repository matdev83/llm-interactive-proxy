from __future__ import annotations

from src.core.config.app_config import AppConfig
from src.core.config.models.access_mode import AccessMode, AccessModeConfig
from src.core.domain.request_context import RequestContext
from src.core.services.auth_scope_resolver_service import DefaultAuthScopeResolver


async def _resolve(
    resolver: DefaultAuthScopeResolver,
    *,
    state: dict[str, object] | None = None,
) -> str | None:
    context = RequestContext(
        headers={},
        cookies={},
        state=state or {},
        app_state=None,
    )
    return await resolver.resolve_auth_scope_id(context)


async def test_resolve_auth_scope_from_injected_auth_scope_id() -> None:
    resolver = DefaultAuthScopeResolver(config=AppConfig())

    resolved = await _resolve(
        resolver,
        state={"auth_scope_id": "token-id-123"},
    )

    assert resolved == "token-id-123"


async def test_resolve_auth_scope_from_token_identity_fallback() -> None:
    resolver = DefaultAuthScopeResolver(config=AppConfig())

    resolved = await _resolve(
        resolver,
        state={"authenticated_token_id": "token-id-abc"},
    )

    assert resolved == "token-id-abc"


async def test_resolve_auth_scope_uses_localhost_implicit_scope_when_missing() -> None:
    resolver = DefaultAuthScopeResolver(config=AppConfig())

    resolved = await _resolve(resolver, state={})

    assert resolved == "localhost"


async def test_resolve_auth_scope_returns_none_when_missing_outside_localhost_mode() -> (
    None
):
    config = AppConfig(
        host="0.0.0.0",
        access_mode=AccessModeConfig(mode=AccessMode.MULTI_USER),
    )
    resolver = DefaultAuthScopeResolver(config=config)

    resolved = await _resolve(resolver, state={})

    assert resolved is None


def test_build_continuity_scope_key_scopes_same_client_by_auth_scope() -> None:
    first_scope = DefaultAuthScopeResolver.build_continuity_scope_key(
        auth_scope_id="token-a",
        client_session_id="client-1",
    )
    second_scope = DefaultAuthScopeResolver.build_continuity_scope_key(
        auth_scope_id="token-b",
        client_session_id="client-1",
    )

    assert first_scope == ("token-a", "client-1")
    assert second_scope == ("token-b", "client-1")
    assert first_scope != second_scope


def test_build_continuity_scope_key_requires_auth_scope() -> None:
    no_scope = DefaultAuthScopeResolver.build_continuity_scope_key(
        auth_scope_id=None,
        client_session_id="client-1",
    )

    assert no_scope is None
