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

    def __init__(self, app: FastAPI | None = None,
                 functional_backends: Set[str] | None = None) -> None:
        super().__init__(app, functional_backends)

    def _unset_default_backend(self, state: "ProxyState") -> str:
        if not self.app:
            return ""
        initial_type = getattr(
            self.app.state,
            "initial_backend_type",
            "openrouter")
        self.app.state.backend_type = initial_type
        if initial_type == "gemini":
            self.app.state.backend = self.app.state.gemini_backend
        else:
            self.app.state.backend = self.app.state.openrouter_backend
        return "default-backend unset"

    def _unset_command_prefix(self, state: "ProxyState") -> str:
        if not self.app:
            return ""
        self.app.state.command_prefix = DEFAULT_COMMAND_PREFIX
        return "command prefix unset"

    def _unset_redact_api_keys(self, state: "ProxyState") -> str:
        if not self.app:
            return ""
        self.app.state.api_key_redaction_enabled = (
            self.app.state.default_api_key_redaction_enabled
        )
        return "redact-api-keys-in-prompts unset"

    def execute(self, args: Dict[str, Any],
                state: "ProxyState") -> CommandResult:
        messages: List[str] = []
        persistent_change = False
        keys_to_unset = [k for k, v in args.items() if v is True]

        # unset_actions map keys to (action_function, is_persistent_flag)
        # Action functions should return a message string if successful (and an action was taken),
        # or an empty string if no action was taken (e.g. self.app is None for some app-dependent actions).
        unset_actions = {
            "model": (lambda s: (s.unset_override_model(), "model unset")[1], False),
            "backend": (lambda s: (s.unset_override_backend(), "backend unset")[1], False),
            "default-backend": (self._unset_default_backend, True),
            "project": (lambda s: (s.unset_project(), "project unset")[1], False),
            "project-name": (lambda s: (s.unset_project(), "project unset")[1], False),
            "interactive": (lambda s: (s.unset_interactive_mode(), "interactive mode unset")[1], True),
            "interactive-mode": (lambda s: (s.unset_interactive_mode(), "interactive mode unset")[1], True),
            "command-prefix": (self._unset_command_prefix, True),
            "redact-api-keys-in-prompts": (self._unset_redact_api_keys, True),
            "reasoning-effort": (lambda s: (s.unset_reasoning_effort(), "reasoning effort unset")[1], False),
            "reasoning": (lambda s: (s.unset_reasoning_config(), "reasoning config unset")[1], False),
            "thinking-budget": (lambda s: (s.unset_thinking_budget(), "thinking budget unset")[1], False),
            "gemini-generation-config": (lambda s: (s.unset_gemini_generation_config(), "gemini generation config unset")[1], False),
            "temperature": (lambda s: (s.unset_temperature(), "temperature unset")[1], False),
        }

        for key in keys_to_unset:
            if key in unset_actions:
                action_func, is_action_persistent = unset_actions[key]
                message = action_func(state)

                if message:
                    messages.append(message)
                    # If any action taken was persistent, mark the overall change as persistent.
                    if is_action_persistent:
                        persistent_change = True

        if not messages: # If no messages were generated, no actions were effectively performed.
            return CommandResult(self.name, False, "unset: nothing to do")

        # Save configuration if any persistent change occurred and app context is available.
        if persistent_change and self.app and getattr(self.app.state, "config_manager", None):
            self.app.state.config_manager.save()

        return CommandResult(self.name, True, "; ".join(messages))
