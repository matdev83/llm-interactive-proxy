from __future__ import annotations

import pytest
from src.core.domain.request_context import RequestContext
from src.core.services.session_resolver_service import DefaultSessionResolver


@pytest.mark.asyncio
async def test_resolver_respects_existing_context_session_id() -> None:
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state={},
        session_id="ctx-session",
    )

    resolver = DefaultSessionResolver(None)

    resolved = await resolver.resolve_session_id(context)

    assert resolved == "ctx-session"


@pytest.mark.asyncio
async def test_resolver_generates_unique_session_ids_when_missing() -> None:
    generated_ids = iter(["generated-1", "generated-2"])

    resolver = DefaultSessionResolver(
        None, default_id_factory=lambda: next(generated_ids)
    )

    context_one = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state={},
    )
    context_two = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state={},
    )

    session_id_one = await resolver.resolve_session_id(context_one)
    session_id_two = await resolver.resolve_session_id(context_two)

    assert session_id_one == "generated-1"
    assert session_id_two == "generated-2"
    assert context_one.session_id == "generated-1"
    assert context_two.session_id == "generated-2"


@pytest.mark.asyncio
async def test_resolver_uses_configured_default_when_available() -> None:
    class ConfigWithSession:
        def __init__(self) -> None:
            self.session = type(
                "SessionConfig", (), {"default_session_id": "   pre-set  "}
            )()

    resolver = DefaultSessionResolver(ConfigWithSession())

    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state={},
    )

    session_id = await resolver.resolve_session_id(context)

    assert session_id == "pre-set"
    assert context.session_id == "pre-set"


@pytest.mark.asyncio
async def test_resolver_respects_request_provided_session_id_before_default() -> None:
    class ConfigWithSession:
        def __init__(self) -> None:
            self.session = type(
                "SessionConfig", (), {"default_session_id": "fallback"}
            )()

    resolver = DefaultSessionResolver(ConfigWithSession())

    context = RequestContext(
        headers={"x-session-id": "user-123"},
        cookies={},
        state={},
        app_state={},
    )

    session_id = await resolver.resolve_session_id(context)

    assert session_id == "user-123"
    assert context.session_id == "user-123"
