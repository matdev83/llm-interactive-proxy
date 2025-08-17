from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

from .base import CommandResult, register_command  # Removed BaseCommand
from .failover_base import FailoverBase

if TYPE_CHECKING:
    pass  # No imports needed


@register_command
class CreateFailoverRouteCommand(FailoverBase):
    name = "create-failover-route"
    format = "create-failover-route(name=<name>,policy=k|m|km|mk)"
    description = "Create a new failover route with given policy"
    examples = ["!/create-failover-route(name=myroute,policy=k)"]

    def __init__(
        self, app: FastAPI | None = None, functional_backends: set[str] | None = None
    ) -> None:
        super().__init__(app=app, functional_backends=functional_backends)

    def execute(self, args: Mapping[str, Any], state: Any) -> CommandResult:
        msgs: list[str] = []
        self._ensure_interactive(state, msgs)
        name = args.get("name")
        policy = str(args.get("policy", "")).lower()
        if not name or policy not in {"k", "m", "km", "mk"}:
            return CommandResult(
                self.name, False, "create-failover-route requires name and valid policy"
            )
        state.create_failover_route(name, policy)
        msgs.append(f"failover route {name} created with policy {policy}")
        if self.app is not None and getattr(self.app.state, "config_manager", None):
            self.app.state.config_manager.save()
        return CommandResult(self.name, True, "; ".join(msgs))
