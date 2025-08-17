from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

from .base import CommandResult, register_command  # Removed BaseCommand
from .failover_base import FailoverBase

if TYPE_CHECKING:
    pass  # No imports needed


@register_command
class RouteListCommand(FailoverBase):
    name = "route-list"
    format = "route-list(name=<route>)"
    description = "List elements of a failover route"
    examples = ["!/route-list(name=myroute)"]

    def __init__(
        self, app: FastAPI | None = None, functional_backends: set[str] | None = None
    ) -> None:
        super().__init__(app=app, functional_backends=functional_backends)

    def execute(self, args: Mapping[str, Any], state: Any) -> CommandResult:
        msgs: list[str] = []
        self._ensure_interactive(state, msgs)
        name = args.get("name")
        if not name or name not in state.failover_routes:
            return CommandResult(self.name, False, f"route {name} not found")
        elems = state.list_route(name)
        msgs.append(", ".join(elems) if elems else "<empty>")
        return CommandResult(self.name, True, "; ".join(msgs))
