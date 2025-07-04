from __future__ import annotations

from typing import Dict, Any, List, Set

from fastapi import FastAPI

from .base import CommandResult, register_command # Removed BaseCommand
from .failover_base import FailoverBase

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..proxy_logic import ProxyState


@register_command
class RouteClearCommand(FailoverBase):
    name = "route-clear"
    format = "route-clear(name=<route>)"
    description = "Remove all elements from a failover route"
    examples = ["!/route-clear(name=myroute)"]

    def __init__(self, app: FastAPI | None = None, functional_backends: Set[str] | None = None) -> None:
        super().__init__(app=app, functional_backends=functional_backends)

    def execute(self, args: Dict[str, Any], state: "ProxyState") -> CommandResult:
        msgs: List[str] = []
        self._ensure_interactive(state, msgs)
        name = args.get("name")
        if not name or name not in state.failover_routes:
            return CommandResult(self.name, False, f"route {name} not found")
        state.clear_route(name)
        msgs.append(f"route {name} cleared")
        if self.app is not None and getattr(self.app.state, "config_manager", None):
            self.app.state.config_manager.save()
        return CommandResult(self.name, True, "; ".join(msgs))
