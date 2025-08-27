from __future__ import annotations

from typing import Any

import pytest
from src.core.commands.handlers.command_handler import ILegacyCommandHandler
from src.core.domain.command_results import CommandResult
from src.core.domain.session import Session
from src.core.services.legacy_handler_adapter import LegacyHandlerCommandAdapter


class _FakeLegacy(ILegacyCommandHandler):
    @property
    def name(self) -> str:  # type: ignore[override]
        return "demo"

    @property
    def description(self) -> str:  # type: ignore[override]
        return "Demo legacy command"

    @property
    def usage(self) -> str:  # type: ignore[override]
        return "demo([x=1])"

    async def execute(  # type: ignore[override]
        self,
        args: dict[str, str],
        session: Any,
        context: dict[str, Any] | None = None,
    ) -> CommandResult:
        return CommandResult(success=True, message=f"ok:{args.get('x','')}")


@pytest.mark.asyncio
async def test_adapter_exposes_legacy_handler_as_base_command() -> None:
    legacy = _FakeLegacy()
    adapter = LegacyHandlerCommandAdapter(legacy)
    assert adapter.name == "demo"
    assert adapter.description.startswith("Demo")
    assert adapter.format.startswith("demo(")

    # Provide a real Session to satisfy adapter type signature
    res = await adapter.execute({"x": 5}, Session(session_id="s1"))
    assert res.success
    assert "ok:5" in res.message
