import pytest

from src.core.domain.request_context import RequestContext
from src.core.services.session_resolver_service import DefaultSessionResolver


@pytest.mark.asyncio
async def test_resolver_prefers_explicit_header_session_id() -> None:
    context = RequestContext(
        headers={"x-session-id": "explicit-session"},
        cookies={},
        state={},
        app_state=None,
    )

    resolver = DefaultSessionResolver()

    resolved = await resolver.resolve_session_id(context)

    assert resolved == "explicit-session"


@pytest.mark.asyncio
async def test_resolver_generates_unique_session_id_when_missing() -> None:
    context = RequestContext(headers={}, cookies={}, state={}, app_state=None)
    resolver = DefaultSessionResolver()

    generated_first = await resolver.resolve_session_id(context)
    generated_second = await resolver.resolve_session_id(context)

    assert generated_first == generated_second
    assert generated_first.startswith("default-")

    new_context = RequestContext(headers={}, cookies={}, state={}, app_state=None)
    new_generated = await resolver.resolve_session_id(new_context)

    assert new_generated.startswith("default-")
    assert new_generated != generated_first


class _ConfigWithCustomDefault:
    class session:  # type: ignore[too-few-public-methods]
        default_session_id = "custom-prefix"


@pytest.mark.asyncio
async def test_resolver_uses_configured_prefix_for_generated_ids() -> None:
    context = RequestContext(headers={}, cookies={}, state={}, app_state=None)
    resolver = DefaultSessionResolver(_ConfigWithCustomDefault())

    generated = await resolver.resolve_session_id(context)

    assert generated.startswith("custom-prefix-")
