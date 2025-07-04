from __future__ import annotations

from typing import Dict, Any, List, Set, Callable # Added Callable

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

    # Returns: (action_taken_for_this_key, is_persistent_change)
    UnsetHandler = Callable[[List[str], "ProxyState", List[str]], tuple[bool, bool]]
    UnsetHandlerNoState = Callable[[List[str], List[str]], tuple[bool, bool]]

    def _handle_model_unset(self, keys_to_unset: List[str], state: "ProxyState", messages: List[str]) -> tuple[bool, bool]:
        if "model" in keys_to_unset:
            state.unset_override_model()
            messages.append("model unset")
            return True, False # action_taken, not persistent
        return False, False

    def _handle_backend_unset(self, keys_to_unset: List[str], state: "ProxyState", messages: List[str]) -> tuple[bool, bool]:
        if "backend" in keys_to_unset:
            state.unset_override_backend()
            messages.append("backend unset")
            return True, False # action_taken, not persistent
        return False, False

    def _handle_default_backend_unset(self, keys_to_unset: List[str], messages: List[str]) -> tuple[bool, bool]:
        if "default-backend" in keys_to_unset and self.app:
            default_type = getattr(self.app.state, "initial_backend_type", None)
            if default_type: # pragma: no branch
                self.app.state.backend_type = default_type
                if default_type == "gemini": # pragma: no cover
                    self.app.state.backend = self.app.state.gemini_backend
                else: # pragma: no cover
                    self.app.state.backend = self.app.state.openrouter_backend
            messages.append("default-backend unset to initial default")
            return True, True # action_taken, persistent_change
        return False, False

    def _handle_project_unset(self, keys_to_unset: List[str], state: "ProxyState", messages: List[str]) -> tuple[bool, bool]:
        # Handles "project" or "project-name"
        if any(k in keys_to_unset for k in ("project", "project-name")):
            state.unset_project()
            messages.append("project unset")
            return True, False # action_taken, not persistent
        return False, False

    def _handle_interactive_mode_unset(self, keys_to_unset: List[str], state: "ProxyState", messages: List[str]) -> tuple[bool, bool]:
        # Handles "interactive" or "interactive-mode"
        if any(k in keys_to_unset for k in ("interactive", "interactive-mode")):
            state.unset_interactive_mode() # Resets to default based on app state
            messages.append("interactive mode unset (reverted to default)")
            return True, True # action_taken, persistent_change
        return False, False

    def _handle_command_prefix_unset(self, keys_to_unset: List[str], messages: List[str]) -> tuple[bool, bool]:
        if "command-prefix" in keys_to_unset and self.app:
            self.app.state.command_prefix = DEFAULT_COMMAND_PREFIX
            messages.append(f"command prefix unset (reverted to '{DEFAULT_COMMAND_PREFIX}')")
            return True, True # action_taken, persistent_change
        return False, False

    def _handle_redact_api_keys_unset(self, keys_to_unset: List[str], messages: List[str]) -> tuple[bool, bool]:
        if "redact-api-keys-in-prompts" in keys_to_unset and self.app:
            self.app.state.api_key_redaction_enabled = self.app.state.default_api_key_redaction_enabled
            messages.append(f"API key redaction in prompts unset (reverted to default: {self.app.state.default_api_key_redaction_enabled})")
            return True, True # action_taken, persistent_change
        return False, False

    def execute(self, args: Dict[str, Any], state: "ProxyState") -> CommandResult:
        messages: List[str] = []
        overall_action_taken = False
        persistent_change_made = False

        keys_to_unset = [k for k, v in args.items() if v is True]

        if not keys_to_unset:
            return CommandResult(self.name, False, "unset: no parameters provided to unset")

        handlers: List[self.UnsetHandler | self.UnsetHandlerNoState] = [
            self._handle_model_unset,
            self._handle_backend_unset,
            lambda ku, _s, m: self._handle_default_backend_unset(ku, m), # Adapt NoState to UnsetHandler
            self._handle_project_unset,
            self._handle_interactive_mode_unset,
            lambda ku, _s, m: self._handle_command_prefix_unset(ku, m),   # Adapt NoState to UnsetHandler
            lambda ku, _s, m: self._handle_redact_api_keys_unset(ku, m), # Adapt NoState to UnsetHandler
        ]

        for handler_method in handlers:
            action_by_handler, persistent_by_handler = handler_method(keys_to_unset, state, messages)
            if action_by_handler:
                overall_action_taken = True
            if persistent_by_handler:
                persistent_change_made = True

        if not overall_action_taken:
            # This means none of the known keys were present in `keys_to_unset`
            # or the provided keys in `args` were not recognized by any handler.
            # The `keys_to_unset` list only contains keys that were `True` in `args`.
            # If `keys_to_unset` was populated but `overall_action_taken` is false,
            # it implies the keys were not among those handled (e.g., "unset(unknownkey)")
            return CommandResult(self.name, False, "unset: no recognized parameters were specified to unset")

        if persistent_change_made and self.app and hasattr(self.app.state, "config_manager") and self.app.state.config_manager:
            self.app.state.config_manager.save()

        return CommandResult(self.name, True, "; ".join(messages))
