from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Set

from fastapi import FastAPI

from ..command_prefix import validate_command_prefix
from .base import BaseCommand, CommandResult, register_command

if TYPE_CHECKING:
    from ..proxy_logic import ProxyState

logger = logging.getLogger(__name__)


@register_command
class SetCommand(BaseCommand):
    name = "set"
    format = "set(key=value, ...)"
    description = "Set session or global configuration values"
    examples = [
        "!/set(model=openrouter:gpt-4)",
        "!/set(interactive=true)",
    ]

    def __init__(
        self, app: FastAPI | None = None, functional_backends: Set[str] | None = None
    ) -> None:
        super().__init__(app, functional_backends)

    def _parse_bool(self, value: str) -> bool | None:
        val = value.strip().lower()
        if val in ("true", "1", "yes", "on"):
            return True
        if val in ("false", "0", "no", "off", "none"):
            return False
        return None

    def execute(self, args: Dict[str, Any], state: "ProxyState") -> CommandResult:
        logger.debug(
            f"SetCommand.execute called with args: {args}, functional_backends: {self.functional_backends}"
        )
        messages: List[str] = []
        handled = False
        backend_set_failed = False
        if isinstance(args.get("backend"), str):
            backend_val = args["backend"].strip().lower()
            logger.debug(f"SetCommand: Processing 'backend' argument: {backend_val}")
            if backend_val not in {"openrouter", "gemini"}:
                return CommandResult(
                    self.name, False, f"backend {backend_val} not supported"
                )
            if backend_val not in self.functional_backends:
                state.unset_override_backend()
                backend_set_failed = True
                return CommandResult(
                    self.name, False, f"backend {backend_val} not functional"
                )
            logger.debug(
                f"SetCommand: About to call state.set_override_backend with {backend_val}"
            )
            state.set_override_backend(backend_val)
            handled = True
            messages.append(f"backend set to {backend_val}")
        persistent_change = False
        if isinstance(args.get("default-backend"), str):
            backend_val = args["default-backend"].strip().lower()
            if backend_val not in {"openrouter", "gemini"}:
                return CommandResult(
                    self.name, False, f"backend {backend_val} not supported"
                )
            if backend_val not in self.functional_backends:
                return CommandResult(
                    self.name, False, f"backend {backend_val} not functional"
                )
            if self.app is not None:
                self.app.state.backend_type = backend_val
                if backend_val == "gemini":
                    self.app.state.backend = self.app.state.gemini_backend
                else:
                    self.app.state.backend = self.app.state.openrouter_backend
                if getattr(self.app.state, "config_manager", None):
                    self.app.state.config_manager.save()
            handled = True
            messages.append(f"default backend set to {backend_val}")
            persistent_change = True
        if not backend_set_failed and isinstance(args.get("model"), str):
            model_val = args["model"].strip()
            if ":" not in model_val:
                return CommandResult(
                    self.name, False, "model must be specified as <backend>:<model>"
                )
            backend_part, model_name = model_val.split(":", 1)
            backend_part = backend_part.lower()

            backend_obj = None
            if self.app is not None:
                try:
                    backend_obj = getattr(
                        self.app.state, f"{backend_part}_backend", None
                    )
                except Exception:
                    backend_obj = None

            available = backend_obj.get_available_models() if backend_obj else []

            if model_name in available:
                state.set_override_model(backend_part, model_name)
                handled = True
                messages.append(f"model set to {backend_part}:{model_name}")
            elif state.interactive_mode:
                return CommandResult(
                    self.name,
                    False,
                    f"model {backend_part}:{model_name} not available",
                )
            else:
                state.set_override_model(backend_part, model_name, invalid=True)
                handled = True

        if isinstance(args.get("project"), str) or isinstance(
            args.get("project-name"), str
        ):
            name_val = str(args.get("project") or args.get("project-name"))
            state.set_project(name_val)
            handled = True
            messages.append(f"project set to {name_val}")
        for key in ("interactive", "interactive-mode"):
            if isinstance(args.get(key), str):
                val = self._parse_bool(args[key])
                if val is not None:
                    state.set_interactive_mode(val)
                    handled = True
                    messages.append(f"interactive mode set to {val}")
                    persistent_change = True
        if (
            isinstance(args.get("redact-api-keys-in-prompts"), str)
            and self.app is not None
        ):
            val = self._parse_bool(args["redact-api-keys-in-prompts"])
            if val is not None:
                self.app.state.api_key_redaction_enabled = val
                handled = True
                messages.append(f"redact-api-keys-in-prompts set to {val}")
                persistent_change = True
        if isinstance(args.get("command-prefix"), str) and self.app is not None:
            new_prefix = args["command-prefix"]
            error = validate_command_prefix(new_prefix)
            if error:
                return CommandResult(self.name, False, error)
            self.app.state.command_prefix = new_prefix
            handled = True
            messages.append(f"command prefix set to {new_prefix}")
            persistent_change = True
        if not handled:
            return CommandResult(self.name, False, "set: no valid parameters")
        if (
            persistent_change
            and self.app is not None
            and getattr(self.app.state, "config_manager", None)
        ):
            self.app.state.config_manager.save()
        return CommandResult(self.name, True, "; ".join(messages))
