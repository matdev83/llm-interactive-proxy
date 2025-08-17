from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

from .base import BaseCommand, CommandResult, register_command

if TYPE_CHECKING:
    pass  # No imports needed

logger = logging.getLogger(__name__)


@register_command
class OneoffCommand(BaseCommand):
    name = "oneoff"
    aliases: list[str] = ["one-off"]
    format = "oneoff(backend/model)"
    description = (
        "Sets a one-time override for the backend and model for the next request."
    )
    examples = [
        "!/oneoff(openrouter/gpt-4)",
        "!/one-off(gemini/gemini-pro)",
    ]

    def __init__(
        self, app: FastAPI | None = None, functional_backends: set[str] | None = None
    ) -> None:
        super().__init__(app, functional_backends)

    def execute(self, args: Mapping[str, Any], state: Any) -> CommandResult:
        if not args:
            return CommandResult(
                self.name, False, "oneoff command requires a backend/model argument."
            )

        arg_key = next(iter(args.keys()))

        # Use robust parsing that handles both slash and colon syntax
        from src.models import parse_model_backend

        backend, model = parse_model_backend(arg_key)
        if not backend:
            return CommandResult(
                self.name, False, "Invalid format. Use backend/model or backend:model."
            )
        backend = backend.strip()
        model = model.strip()

        if not backend or not model:
            return CommandResult(self.name, False, "Backend and model cannot be empty.")

        state.set_oneoff_route(backend, model)
        return CommandResult(
            self.name, True, f"One-off route set to {backend}/{model}."
        )
