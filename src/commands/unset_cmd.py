from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Mapping

from fastapi import FastAPI

from ..constants import DEFAULT_COMMAND_PREFIX
from .base import BaseCommand, CommandResult, register_command

if TYPE_CHECKING:
    from src.proxy_logic import ProxyState


@register_command
class UnsetCommand(BaseCommand):
    name = "unset"
    format = "unset(key1, key2, ...)"
    description = "Unset previously configured options"
    examples = [
        "!/unset(model)",
        "!/unset(interactive)",
        "!/unset(tool-loop-detection)",
        "!/unset(tool-loop-max-repeats, tool-loop-ttl, tool-loop-mode)",
    ]

    def __init__(
        self, app: FastAPI | None = None, functional_backends: set[str] | None = None
    ) -> None:
        super().__init__(app, functional_backends)

    def _unset_default_backend(self, state: ProxyState) -> str:
        if not self.app:
            return ""
        initial_type = getattr(self.app.state, "initial_backend_type", "openrouter")
        self.app.state.backend_type = initial_type
        if initial_type == "gemini":
            self.app.state.backend = self.app.state.gemini_backend
        else:
            self.app.state.backend = self.app.state.openrouter_backend
        return "default-backend unset"

    def _unset_command_prefix(self, state: ProxyState) -> str:
        if not self.app:
            return ""
        self.app.state.command_prefix = DEFAULT_COMMAND_PREFIX
        return "command prefix unset"

    def _unset_redact_api_keys(self, state: ProxyState) -> str:
        if not self.app:
            return ""
        self.app.state.api_key_redaction_enabled = (
            self.app.state.default_api_key_redaction_enabled
        )
        return "redact-api-keys-in-prompts unset"

    def _create_unset_action(
        self, method_name: str, message: str
    ) -> Callable[[ProxyState], str]:
        """Create an unset action that calls a method on ProxyState and returns a message."""

        def action(state: ProxyState) -> str:
            getattr(state, method_name)()
            return message

        return action

    def execute(self, args: Mapping[str, Any], state: ProxyState) -> CommandResult:
        keys_to_unset = [k for k, v in args.items() if v is True]
        actions = self._build_unset_actions()
        messages, persistent_change = self._apply_unset_actions(
            keys_to_unset, state, actions
        )
        if not messages:
            return CommandResult(self.name, False, "unset: nothing to do")
        self._save_if_persistent(persistent_change)
        return CommandResult(self.name, True, "; ".join(messages))

    def _build_unset_actions(
        self,
    ) -> dict[str, tuple[Callable[[ProxyState], str], bool]]:
        # type: ignore[func-returns-value]
        return {
            "model": (
                self._create_unset_action("unset_override_model", "model unset"),
                False,
            ),
            "backend": (
                self._create_unset_action("unset_override_backend", "backend unset"),
                False,
            ),
            "default-backend": (self._unset_default_backend, True),
            "project": (
                self._create_unset_action("unset_project", "project unset"),
                False,
            ),
            "project-name": (
                self._create_unset_action("unset_project", "project unset"),
                False,
            ),
            "project-dir": (
                self._create_unset_action("unset_project_dir", "project-dir unset"),
                False,
            ),
            "dir": (
                self._create_unset_action("unset_project_dir", "project-dir unset"),
                False,
            ),
            "project-directory": (
                self._create_unset_action(
                    "unset_project_dir", "project-directory unset"
                ),
                False,
            ),
            "interactive": (
                self._create_unset_action(
                    "unset_interactive_mode", "interactive mode unset"
                ),
                True,
            ),
            "interactive-mode": (
                self._create_unset_action(
                    "unset_interactive_mode", "interactive mode unset"
                ),
                True,
            ),
            "command-prefix": (self._unset_command_prefix, True),
            "redact-api-keys-in-prompts": (self._unset_redact_api_keys, True),
            "reasoning-effort": (
                self._create_unset_action(
                    "unset_reasoning_effort", "reasoning effort unset"
                ),
                False,
            ),
            "reasoning": (
                self._create_unset_action(
                    "unset_reasoning_config", "reasoning config unset"
                ),
                False,
            ),
            "thinking-budget": (
                self._create_unset_action(
                    "unset_thinking_budget", "thinking budget unset"
                ),
                False,
            ),
            "gemini-generation-config": (
                self._create_unset_action(
                    "unset_gemini_generation_config", "gemini generation config unset"
                ),
                False,
            ),
            "temperature": (
                self._create_unset_action("unset_temperature", "temperature unset"),
                False,
            ),
            "openai_url": (
                self._create_unset_action("unset_openai_url", "OpenAI URL unset"),
                False,
            ),
            "loop-detection": (
                self._create_unset_action(
                    "unset_loop_detection_enabled", "loop detection unset"
                ),
                False,
            ),
            "tool-loop-detection": (
                self._create_unset_action(
                    "unset_tool_loop_detection_enabled",
                    "tool call loop detection unset",
                ),
                False,
            ),
            "tool-loop-max-repeats": (
                self._create_unset_action(
                    "unset_tool_loop_max_repeats", "tool call loop max repeats unset"
                ),
                False,
            ),
            "tool_loop_max_repeats": (
                self._create_unset_action(
                    "unset_tool_loop_max_repeats", "tool call loop max repeats unset"
                ),
                False,
            ),
            "tool-loop-repeats": (
                self._create_unset_action(
                    "unset_tool_loop_max_repeats", "tool call loop max repeats unset"
                ),
                False,
            ),
            "tool-loop-ttl": (
                self._create_unset_action(
                    "unset_tool_loop_ttl_seconds", "tool call loop TTL seconds unset"
                ),
                False,
            ),
            "tool-loop-ttl-seconds": (
                self._create_unset_action(
                    "unset_tool_loop_ttl_seconds", "tool call loop TTL seconds unset"
                ),
                False,
            ),
            "tool_loop_ttl_seconds": (
                self._create_unset_action(
                    "unset_tool_loop_ttl_seconds", "tool call loop TTL seconds unset"
                ),
                False,
            ),
            "tool-loop-mode": (
                self._create_unset_action(
                    "unset_tool_loop_mode", "tool call loop mode unset"
                ),
                False,
            ),
            "tool_loop_mode": (
                self._create_unset_action(
                    "unset_tool_loop_mode", "tool call loop mode unset"
                ),
                False,
            ),
        }

    def _apply_unset_actions(
        self,
        keys_to_unset: list[str],
        state: ProxyState,
        actions: dict[str, tuple[Callable[[ProxyState], str], bool]],
    ) -> tuple[list[str], bool]:
        messages: list[str] = []
        persistent_change = False
        for key in keys_to_unset:
            if key not in actions:
                continue
            action_func, is_persistent = actions[key]
            message = action_func(state)
            if not message:
                continue
            messages.append(message)
            if is_persistent:
                persistent_change = True
        return messages, persistent_change

    def _save_if_persistent(self, persistent_change: bool) -> None:
        if not persistent_change or not self.app:
            return
        config_manager = getattr(self.app.state, "config_manager", None)
        if config_manager:
            config_manager.save()
