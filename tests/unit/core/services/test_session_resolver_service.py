from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.domain.request_context import RequestContext
from src.core.services.session_resolver_service import DefaultSessionResolver


@pytest.mark.asyncio
async def test_resolver_prefers_context_session_id() -> None:
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state={},
        session_id="context-session",
    )
    resolver = DefaultSessionResolver()

    resolved = await resolver.resolve_session_id(context)

    assert resolved == "context-session"
    assert context.session_id == "context-session"


@pytest.mark.asyncio
async def test_resolver_generates_unique_session_id_when_missing() -> None:
    resolver = DefaultSessionResolver()
    context_one = RequestContext(headers={}, cookies={}, state={}, app_state={})
    context_two = RequestContext(headers={}, cookies={}, state={}, app_state={})

    resolved_one = await resolver.resolve_session_id(context_one)
    resolved_two = await resolver.resolve_session_id(context_two)

    assert resolved_one
    assert resolved_two
    assert resolved_one != resolved_two
    assert context_one.session_id == resolved_one
    assert context_two.session_id == resolved_two


@pytest.mark.asyncio
async def test_resolver_uses_configured_default_when_available() -> None:
    config = SimpleNamespace(
        session=SimpleNamespace(default_session_id="configured-default")
    )
    resolver = DefaultSessionResolver(config)
    context = RequestContext(headers={}, cookies={}, state={}, app_state={})

    resolved = await resolver.resolve_session_id(context)

    assert resolved == "configured-default"
    assert context.session_id == "configured-default"