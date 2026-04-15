"""ACP workspace gating on BackendModelResolver.resolve_target."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from src.connectors.acp_core.workspace_policy import ACP_MISSING_PROJECT_WORKSPACE_CODE
from src.core.common.exceptions import RoutingError
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.session import Session, SessionState

from tests.unit.core.services.test_backend_model_resolver_composite_entrypoint import (
    _build_resolver_with_real_composite,
    _context,
    _request,
)


def _request_with_session(model: str, session_id: str) -> ChatRequest:
    return ChatRequest(
        model=model,
        messages=[ChatMessage(role="user", content="hello")],
        extra_body={"session_id": session_id},
    )


@pytest.mark.asyncio
async def test_acp_backend_raises_routing_error_without_workspace() -> None:
    resolver = _build_resolver_with_real_composite()
    with pytest.raises(RoutingError) as exc_info:
        await resolver.resolve_target(
            _request("gemini-cli-acp:gemini-2.5-flash"),
            context=_context("main"),
        )
    details = exc_info.value.details
    assert isinstance(details, dict)
    assert details.get("code") == ACP_MISSING_PROJECT_WORKSPACE_CODE
    assert details.get("category") == "validation"


@pytest.mark.asyncio
async def test_acp_backend_succeeds_with_extra_body_project_dir(
    tmp_path: Path,
) -> None:
    ws = tmp_path / "repo"
    ws.mkdir()
    resolver = _build_resolver_with_real_composite()
    req = ChatRequest(
        model="gemini-cli-acp:gemini-2.5-flash",
        messages=[ChatMessage(role="user", content="hello")],
        extra_body={"project_dir": str(ws)},
    )
    target = await resolver.resolve_target(req, context=_context("main"))
    assert target.backend == "gemini-cli-acp"
    assert target.model == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_acp_backend_succeeds_with_session_project_dir(tmp_path: Path) -> None:
    ws = tmp_path / "sess_ws"
    ws.mkdir()
    session = Session(
        session_id="s-acp",
        state=SessionState(project_dir=str(ws)),
    )
    resolver = _build_resolver_with_real_composite()
    resolver._session_service.get_session = AsyncMock(return_value=session)
    resolver._session_service.update_session = AsyncMock()

    target = await resolver.resolve_target(
        _request_with_session("gemini-cli-acp:gemini-2.5-flash", "s-acp"),
        context=_context("main"),
    )
    assert target.backend == "gemini-cli-acp"


@pytest.mark.asyncio
async def test_composite_failover_skips_acp_without_workspace() -> None:
    """Failover uses top-level ``|`` (``^`` is weighted random, not failover)."""
    resolver = _build_resolver_with_real_composite()
    resolver._session_service.update_session = AsyncMock()
    target = await resolver.resolve_target(
        _request("gemini-cli-acp:gemini-2.5-flash|openai:gpt-4o-mini"),
        context=_context("main"),
    )
    assert target.backend == "openai"
    assert target.model == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_composite_failover_openai_first_never_tries_acp() -> None:
    resolver = _build_resolver_with_real_composite()
    resolver._session_service.update_session = AsyncMock()
    target = await resolver.resolve_target(
        _request("openai:gpt-4o-mini|gemini-cli-acp:gemini-2.5-flash"),
        context=_context("main"),
    )
    assert target.backend == "openai"
