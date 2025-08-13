from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

from fastapi import FastAPI

from .base import CommandResult, register_command  # Removed BaseCommand
from .failover_base import FailoverBase

if TYPE_CHECKING:
    from src.proxy_logic import ProxyState


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

    def execute(self, args: Mapping[str, Any], state: ProxyState) -> CommandResult:
        msgs: list[str] = []
        self._ensure_interactive(state, msgs)
        data = state.list_routes()
        if not data:
            msgs.append("no failover routes defined")
        else:
            msgs.append(", ".join(f"{n}:{p}" for n, p in data.items()))
        return CommandResult(self.name, True, "; ".join(msgs))
