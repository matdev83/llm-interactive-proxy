from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

from .base import CommandResult, register_command  # Removed BaseCommand
from .failover_base import FailoverBase

if TYPE_CHECKING:
    pass  # No imports needed


@register_command
class ListFailoverRoutesCommand(FailoverBase):
    name = "list-failover-routes"
    format = "list-failover-routes"
    description = "List configured failover routes"
    examples = ["!/list-failover-routes"]

    def __init__(
        self, app: FastAPI | None = None, functional_backends: set[str] | None = None
    ) -> None:
        super().__init__(app=app, functional_backends=functional_backends)

    def execute(self, args: Mapping[str, Any], state: Any) -> CommandResult:
        msgs: list[str] = []
        self._ensure_interactive(state, msgs)
        data = state.list_routes()
        if not data:
            msgs.append("no failover routes defined")
        else:
            msgs.append(", ".join(f"{n}:{p}" for n, p in data.items()))
        return CommandResult(self.name, True, "; ".join(msgs))
