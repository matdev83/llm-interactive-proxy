from __future__ import annotations

import types
from uuid import UUID
from unittest.mock import patch

import pytest

from src.core.domain.request_context import RequestContext
from src.core.services.session_resolver_service import DefaultSessionResolver


@pytest.mark.asyncio
async def test_resolver_prefers_context_session_id() -> None:
    resolver = DefaultSessionResolver(config=None)
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        session_id="explicit-session",
    )

    session_id = await resolver.resolve_session_id(context)

    assert session_id == "explicit-session"


@pytest.mark.asyncio
async def test_resolver_uses_configured_default() -> None:
    config = types.SimpleNamespace(
        session=types.SimpleNamespace(default_session_id="configured-default")
    )
    resolver = DefaultSessionResolver(config=config)
    context = RequestContext(headers={}, cookies={}, state=None, app_state=None)

    session_id = await resolver.resolve_session_id(context)

    assert session_id == "configured-default"


@pytest.mark.asyncio
async def test_resolver_generates_unique_session_ids_when_missing() -> None:
    resolver = DefaultSessionResolver(config=None)
    context_one = RequestContext(headers={}, cookies={}, state=None, app_state=None)
    context_two = RequestContext(headers={}, cookies={}, state=None, app_state=None)

    first_uuid = UUID("12345678-1234-5678-1234-567812345678")
    second_uuid = UUID("87654321-4321-8765-4321-876543218765")

    with patch(
        "src.core.services.session_resolver_service.uuid.uuid4",
        side_effect=[first_uuid, second_uuid],
    ):
        first_id = await resolver.resolve_session_id(context_one)
        second_id = await resolver.resolve_session_id(context_two)

    assert first_id == str(first_uuid)
    assert second_id == str(second_uuid)
    assert first_id != second_id