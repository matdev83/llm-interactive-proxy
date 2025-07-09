from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, List, Mapping, Set, Optional

from fastapi import FastAPI

from .base import BaseCommand, CommandResult, register_command

if TYPE_CHECKING:
    from ..proxy_logic import ProxyState

logger = logging.getLogger(__name__)


@register_command
class OneoffCommand(BaseCommand):
    name = "oneoff"
    aliases: List[str] = ["one-off"]
    format = "oneoff(backend/model)"
    description = "Sets a one-time override for the backend and model for the next request."
    examples = [
        "!/oneoff(openrouter/gpt-4)",
        "!/one-off(gemini/gemini-pro)",
    ]

    def __init__(self, app: Optional[FastAPI] = None, functional_backends: Optional[Set[str]] = None) -> None:
        super().__init__(app, functional_backends)

    def execute(self, args: Mapping[str, Any], state: "ProxyState") -> CommandResult:
        if not args:
            return CommandResult(self.name, False, "oneoff command requires a backend/model argument.")

        arg_key = list(args.keys())[0]
        if "/" not in arg_key:
            return CommandResult(self.name, False, "Invalid format. Use backend/model.")

        backend, model = arg_key.split("/", 1)
        backend = backend.strip()
        model = model.strip()

        if not backend or not model:
            return CommandResult(self.name, False, "Backend and model cannot be empty.")

        state.set_oneoff_route(backend, model)
        return CommandResult(self.name, True, f"One-off route set to {backend}:{model}.")
