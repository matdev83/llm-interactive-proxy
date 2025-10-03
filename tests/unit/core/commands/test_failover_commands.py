"""Tests for failover command edge cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from src.core.domain.commands.failover_commands import RoutePrependCommand
from src.core.domain.session import Session
from src.core.interfaces.state_provider_interface import (
    ISecureStateAccess,
    ISecureStateModification,
)


pytestmark = pytest.mark.anyio("asyncio")


@pytest.fixture
def anyio_backend() -> str:
    """Force AnyIO to use the asyncio backend in environments without trio."""
    return "asyncio"


@dataclass
class _DummyState(ISecureStateAccess, ISecureStateModification):
    """Minimal state service satisfying command dependencies."""

    routes: list[dict[str, Any]] | None = None

    def get_command_prefix(self) -> str | None:  # pragma: no cover - interface shim
        return "!/"

    def get_api_key_redaction_enabled(self) -> bool:  # pragma: no cover - shim
        return False

    def get_disable_interactive_commands(self) -> bool:  # pragma: no cover - shim
        return False

    def get_failover_routes(self) -> list[dict[str, Any]] | None:  # pragma: no cover
        return self.routes

    def update_command_prefix(self, prefix: str) -> None:  # pragma: no cover
        return None

    def update_api_key_redaction(self, enabled: bool) -> None:  # pragma: no cover
        return None

    def update_interactive_commands(self, disabled: bool) -> None:  # pragma: no cover
        return None

    def update_failover_routes(self, routes: list[dict[str, Any]]) -> None:  # pragma: no cover
        self.routes = routes


def _make_session_with_route(route_name: str = "route") -> Session:
    session = Session(session_id="test-session")
    backend_config = session.state.backend_config
    session.state = session.state.with_backend_config(
        backend_config.with_failover_route(route_name, "k")
    )
    return session


async def test_route_prepend_handles_dict_context() -> None:
    """Ensure dict-based contexts do not raise attribute errors."""

    session = _make_session_with_route()
    command = RoutePrependCommand(_DummyState(), _DummyState())

    result = await command.execute(
        {"name": "route", "element": "anthropic:claude"},
        session,
        context={"foo": "bar"},
    )

    assert result.success is True
    elements = session.state.backend_config.get_route_elements("route")
    assert elements == ["anthropic:claude"]


async def test_route_prepend_respects_backend_allow_list() -> None:
    """Unsupported backends should still be rejected when metadata is present."""

    class _Factory:
        def __init__(self) -> None:
            self._backend_types = {"openai": object()}

    session = _make_session_with_route()
    command = RoutePrependCommand(_DummyState(), _DummyState())

    context = type("Ctx", (), {"backend_factory": _Factory()})()

    result = await command.execute(
        {"name": "route", "element": "anthropic:claude"},
        session,
        context=context,
    )

    assert result.success is False
    assert "not supported" in result.message
    assert session.state.backend_config.get_route_elements("route") == []
