from __future__ import annotations

from typing import Dict, Any, List, Set

from fastapi import FastAPI

from .base import BaseCommand, CommandResult, register_command
from ..constants import DEFAULT_COMMAND_PREFIX

from typing import TYPE_CHECKING

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

    def __init__(self, app: FastAPI | None = None, functional_backends: Set[str] | None = None) -> None:
        super().__init__(app, functional_backends)

    def _handle_model_unset(self, keys_to_unset: List[str], state: "ProxyState", messages: List[str]) -> bool:
        if "model" in keys_to_unset:
            state.unset_override_model()
            messages.append("model unset")
            return True
        return False

    def _handle_backend_unset(self, keys_to_unset: List[str], state: "ProxyState", messages: List[str]) -> bool:
        if "backend" in keys_to_unset:
            state.unset_override_backend()
            messages.append("backend unset")
            return True
        return False

    def _handle_default_backend_unset(self, keys_to_unset: List[str], messages: List[str]) -> bool:
        if "default-backend" in keys_to_unset and self.app:
            default_type = getattr(self.app.state, "initial_backend_type", None)
            if default_type: # pragma: no branch
                self.app.state.backend_type = default_type
                if default_type == "gemini": # pragma: no cover
                    self.app.state.backend = self.app.state.gemini_backend
                else: # pragma: no cover
                    self.app.state.backend = self.app.state.openrouter_backend
            messages.append("default-backend unset to initial default")
            return True # persistent_change = True
        return False

    def _handle_project_unset(self, keys_to_unset: List[str], state: "ProxyState", messages: List[str]) -> bool:
        if any(k in keys_to_unset for k in ("project", "project-name")):
            state.unset_project()
            messages.append("project unset")
            return True
        return False

    def _handle_interactive_mode_unset(self, keys_to_unset: List[str], state: "ProxyState", messages: List[str]) -> bool:
        if any(k in keys_to_unset for k in ("interactive", "interactive-mode")):
            state.unset_interactive_mode() # Resets to default based on app state
            messages.append("interactive mode unset (reverted to default)")
            return True # persistent_change = True
        return False

    def _handle_command_prefix_unset(self, keys_to_unset: List[str], messages: List[str]) -> bool:
        if "command-prefix" in keys_to_unset and self.app:
            self.app.state.command_prefix = DEFAULT_COMMAND_PREFIX
            messages.append(f"command prefix unset (reverted to '{DEFAULT_COMMAND_PREFIX}')")
            return True # persistent_change = True
        return False

    def _handle_redact_api_keys_unset(self, keys_to_unset: List[str], messages: List[str]) -> bool:
        if "redact-api-keys-in-prompts" in keys_to_unset and self.app:
            self.app.state.api_key_redaction_enabled = self.app.state.default_api_key_redaction_enabled
            messages.append(f"API key redaction in prompts unset (reverted to default: {self.app.state.default_api_key_redaction_enabled})")
            return True # persistent_change = True
        return False

    def execute(self, args: Dict[str, Any], state: "ProxyState") -> CommandResult:
        messages: List[str] = []
        persistent_change_made = False

        # Determine which keys are being requested to be unset
        # In the command parser, valid unset keys are set to True in args
        keys_to_unset = [k for k, v in args.items() if v is True]

        if not keys_to_unset:
            return CommandResult(self.name, False, "unset: no parameters provided to unset")

        action_taken = False

        if self._handle_model_unset(keys_to_unset, state, messages):
            action_taken = True
        if self._handle_backend_unset(keys_to_unset, state, messages):
            action_taken = True

        if self._handle_default_backend_unset(keys_to_unset, messages):
            action_taken = True
            persistent_change_made = True

        if self._handle_project_unset(keys_to_unset, state, messages):
            action_taken = True
            # Project is session-specific, not saved in config by this command

        if self._handle_interactive_mode_unset(keys_to_unset, state, messages):
            action_taken = True
            persistent_change_made = True

        if self._handle_command_prefix_unset(keys_to_unset, messages):
            action_taken = True
            persistent_change_made = True

        if self._handle_redact_api_keys_unset(keys_to_unset, messages):
            action_taken = True
            persistent_change_made = True

        if not action_taken: # Or if messages list is empty, meaning no known keys were unset
            return CommandResult(self.name, False, "unset: no recognized parameters were specified to unset")

        if persistent_change_made and self.app and hasattr(self.app.state, "config_manager") and self.app.state.config_manager:
            self.app.state.config_manager.save()

        return CommandResult(self.name, True, "; ".join(messages))
