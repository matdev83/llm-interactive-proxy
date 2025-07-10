from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Set

from fastapi import FastAPI

from .base import CommandResult, register_command  # Removed BaseCommand
from .failover_base import FailoverBase

if TYPE_CHECKING:
    from ..proxy_logic import ProxyState


@register_command
class RouteAppendCommand(FailoverBase):
    name = "route-append"
    format = "route-append(name=<route>,backend/model,...)"
    description = "Append elements to a failover route"
    examples = ["!/route-append(name=myroute,openrouter/model-a)"]

    def __init__(self, app: FastAPI | None = None,
                 functional_backends: Set[str] | None = None) -> None:
        super().__init__(app=app, functional_backends=functional_backends)

    def execute(self, args: Dict[str, Any],
                state: "ProxyState") -> CommandResult:
        msgs: List[str] = []
        self._ensure_interactive(state, msgs)
        name = args.get("name")
        if not name or name not in state.failover_routes:
            return CommandResult(self.name, False, f"route {name} not found")
        elements = [k for k in args.keys() if k != "name"]
        if not elements:
            return CommandResult(
                self.name, False, "no route elements specified")
        for e in elements:
            # Use robust parsing that handles both slash and colon syntax
            from src.models import parse_model_backend
            backend, model = parse_model_backend(e)
            if not backend:
                continue  # Skip invalid elements
            internal_element = f"{backend}:{model}"
            state.append_route_element(name, internal_element)
        msgs.append(f"elements appended to {name}")
        if self.app is not None and getattr(
                self.app.state, "config_manager", None):
            self.app.state.config_manager.save()
        return CommandResult(self.name, True, "; ".join(msgs))
