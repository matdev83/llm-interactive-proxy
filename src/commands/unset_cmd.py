from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Set

from fastapi import FastAPI

from ..constants import DEFAULT_COMMAND_PREFIX
from .base import BaseCommand, CommandResult, register_command

if TYPE_CHECKING:
    from ..proxy_logic import ProxyState


@register_command
class UnsetCommand(BaseCommand):
    name = "unset"
    format = "unset(key1, key2, ...)"
    description = "Unset previously configured options"
    examples = [
        "!/unset(model)",
        "!/unset(interactive)",
    ]

    def __init__(
        self, app: FastAPI | None = None, functional_backends: Set[str] | None = None
    ) -> None:
        super().__init__(app, functional_backends)

    def execute(self, args: Dict[str, Any], state: "ProxyState") -> CommandResult:
        messages: List[str] = []
        persistent_change = False
        keys_to_unset = [k for k, v in args.items() if v is True]
        if "model" in keys_to_unset:
            state.unset_override_model()
            messages.append("model unset")
        if "backend" in keys_to_unset:
            state.unset_override_backend()
            messages.append("backend unset")
        if "default-backend" in keys_to_unset and self.app:
            initial_type = getattr(self.app.state, "initial_backend_type", "openrouter")
            self.app.state.backend_type = initial_type
            if initial_type == "gemini":
                self.app.state.backend = self.app.state.gemini_backend
            else:
                self.app.state.backend = self.app.state.openrouter_backend
            if getattr(self.app.state, "config_manager", None):
                self.app.state.config_manager.save()
            messages.append("default-backend unset")
            persistent_change = True
        if any(k in keys_to_unset for k in ("project", "project-name")):
            state.unset_project()
            messages.append("project unset")
        if any(k in keys_to_unset for k in ("interactive", "interactive-mode")):
            state.unset_interactive_mode()
            messages.append("interactive mode unset")
            persistent_change = True
        if "command-prefix" in keys_to_unset and self.app:
            self.app.state.command_prefix = DEFAULT_COMMAND_PREFIX
            messages.append("command prefix unset")
            persistent_change = True
        if "redact-api-keys-in-prompts" in keys_to_unset and self.app:
            self.app.state.api_key_redaction_enabled = (
                self.app.state.default_api_key_redaction_enabled
            )
            messages.append("redact-api-keys-in-prompts unset")
            persistent_change = True
        if not keys_to_unset or not messages:
            return CommandResult(self.name, False, "unset: nothing to do")
        if (
            persistent_change
            and self.app
            and getattr(self.app.state, "config_manager", None)
        ):
            self.app.state.config_manager.save()
        return CommandResult(self.name, True, "; ".join(messages))
