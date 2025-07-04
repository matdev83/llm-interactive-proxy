from __future__ import annotations

from typing import Dict, Any, List, Set

from fastapi import FastAPI

from .base import BaseCommand, CommandResult, register_command
from ..command_prefix import validate_command_prefix

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..proxy_logic import ProxyState


@register_command
class SetCommand(BaseCommand):
    name = "set"
    format = "set(key=value, ...)"
    description = "Set session or global configuration values"
    examples = [
        "!/set(model=openrouter:gpt-4)",
        "!/set(interactive=true)",
    ]

    def __init__(self, app: FastAPI | None = None, functional_backends: Set[str] | None = None) -> None:
        super().__init__(app, functional_backends)

    def _parse_bool(self, value: str) -> bool | None:
        val = value.strip().lower()
        if val in ("true", "1", "yes", "on"):
            return True
        if val in ("false", "0", "no", "off", "none"):
            return False
        return None

    def _handle_backend_setting(self, args: Dict[str, Any], state: "ProxyState", messages: List[str]) -> tuple[bool, CommandResult | None]:
        """Handles the 'backend' setting."""
        if isinstance(args.get("backend"), str):
            backend_val = args["backend"].strip().lower()
            if backend_val not in {"openrouter", "gemini"}:
                return False, CommandResult(self.name, False, f"backend {backend_val} not supported")
            if self.functional_backends is not None and backend_val not in self.functional_backends:
                state.unset_override_backend() # Ensure it's unset if previously set
                return True, CommandResult(self.name, False, f"backend {backend_val} not functional") # backend_set_failed = True
            state.set_override_backend(backend_val)
            messages.append(f"backend set to {backend_val}")
            return False, None # Not failed, no immediate return
        return False, None # Not handled or no failure

    def _handle_default_backend_setting(self, args: Dict[str, Any], messages: List[str]) -> tuple[bool, CommandResult | None]:
        """Handles the 'default-backend' setting."""
        if isinstance(args.get("default-backend"), str):
            backend_val = args["default-backend"].strip().lower()
            if backend_val not in {"openrouter", "gemini"}:
                return False, CommandResult(self.name, False, f"default backend {backend_val} not supported")
            if self.functional_backends is not None and backend_val not in self.functional_backends:
                return False, CommandResult(self.name, False, f"default backend {backend_val} not functional")

            if self.app is not None:
                self.app.state.backend_type = backend_val
                if backend_val == "gemini":
                    self.app.state.backend = self.app.state.gemini_backend
                else: # openrouter
                    self.app.state.backend = self.app.state.openrouter_backend
                messages.append(f"default backend set to {backend_val}")
                return True, None # persistent_change = True
        return False, None

    def _handle_model_setting(self, args: Dict[str, Any], state: "ProxyState", messages: List[str], backend_set_failed: bool) -> tuple[bool, CommandResult | None]:
        """Handles the 'model' setting."""
        if not backend_set_failed and isinstance(args.get("model"), str):
            model_val = args["model"].strip()
            if ":" not in model_val:
                return False, CommandResult(self.name, False, "model must be specified as <backend>:<model_name>")

            backend_part, model_name = model_val.split(":", 1)
            backend_part = backend_part.lower()

            backend_obj = None
            if self.app is not None:
                try:
                    backend_obj = getattr(self.app.state, f"{backend_part}_backend", None)
                except AttributeError: # pragma: no cover
                    backend_obj = None # Should not happen if backend validation is done first

            available_models = backend_obj.get_available_models() if backend_obj else []

            if model_name in available_models:
                state.set_override_model(backend_part, model_name)
                messages.append(f"model set to {backend_part}:{model_name}")
            elif state.interactive_mode:
                return False, CommandResult(self.name, False, f"model {backend_part}:{model_name} not available")
            else: # Non-interactive, allow setting invalid model to show error later
                state.set_override_model(backend_part, model_name, invalid=True)
            return True, None # handled = True
        return False, None


    def _handle_project_setting(self, args: Dict[str, Any], state: "ProxyState", messages: List[str]) -> bool:
        """Handles 'project' or 'project-name' setting."""
        project_arg = args.get("project") or args.get("project-name")
        if isinstance(project_arg, str):
            name_val = project_arg.strip()
            state.set_project(name_val)
            messages.append(f"project set to {name_val}")
            return True
        return False

    def _handle_interactive_mode_setting(self, args: Dict[str, Any], state: "ProxyState", messages: List[str]) -> tuple[bool, bool]:
        """Handles 'interactive' or 'interactive-mode' setting. Returns (handled, persistent_change)."""
        for key in ("interactive", "interactive-mode"):
            if isinstance(args.get(key), str):
                val = self._parse_bool(args[key])
                if val is not None:
                    state.set_interactive_mode(val)
                    messages.append(f"interactive mode set to {val}")
                    return True, True # handled, persistent_change
        return False, False

    def _handle_redact_api_keys_setting(self, args: Dict[str, Any], messages: List[str]) -> tuple[bool, bool]:
        """Handles 'redact-api-keys-in-prompts'. Returns (handled, persistent_change)."""
        if isinstance(args.get("redact-api-keys-in-prompts"), str) and self.app is not None:
            val = self._parse_bool(args["redact-api-keys-in-prompts"])
            if val is not None:
                self.app.state.api_key_redaction_enabled = val
                messages.append(f"API key redaction in prompts set to {val}")
                return True, True # handled, persistent_change
        return False, False

    def _handle_command_prefix_setting(self, args: Dict[str, Any], messages: List[str]) -> tuple[bool, bool, CommandResult | None]:
        """Handles 'command-prefix'. Returns (handled, persistent_change, error_result)."""
        if isinstance(args.get("command-prefix"), str) and self.app is not None:
            new_prefix = args["command-prefix"]
            error = validate_command_prefix(new_prefix)
            if error:
                return False, False, CommandResult(self.name, False, error)
            self.app.state.command_prefix = new_prefix
            messages.append(f"command prefix set to '{new_prefix}'")
            return True, True, None # handled, persistent_change, no error
        return False, False, None

    def execute(self, args: Dict[str, Any], state: "ProxyState") -> CommandResult:
        messages: List[str] = []
        any_handled = False
        persistent_change_made = False

        backend_set_failed, cmd_result = self._handle_backend_setting(args, state, messages)
        if cmd_result: return cmd_result
        if args.get("backend") is not None: any_handled = True

        persistent, cmd_result = self._handle_default_backend_setting(args, messages)
        if cmd_result: return cmd_result
        if persistent: persistent_change_made = True
        if args.get("default-backend") is not None: any_handled = True

        handled_model, cmd_result = self._handle_model_setting(args, state, messages, backend_set_failed)
        if cmd_result: return cmd_result
        if handled_model: any_handled = True

        if self._handle_project_setting(args, state, messages):
            any_handled = True
            # Project setting is not considered persistent for config saving here, it's session-specific.

        handled_interactive, persistent_interactive = self._handle_interactive_mode_setting(args, state, messages)
        if handled_interactive: any_handled = True
        if persistent_interactive: persistent_change_made = True

        handled_redact, persistent_redact = self._handle_redact_api_keys_setting(args, messages)
        if handled_redact: any_handled = True
        if persistent_redact: persistent_change_made = True

        handled_prefix, persistent_prefix, cmd_result = self._handle_command_prefix_setting(args, messages)
        if cmd_result: return cmd_result
        if handled_prefix: any_handled = True
        if persistent_prefix: persistent_change_made = True

        if not any_handled:
            return CommandResult(self.name, False, "set: no valid or recognized parameters provided")

        if persistent_change_made and self.app is not None and hasattr(self.app.state, "config_manager") and self.app.state.config_manager:
            self.app.state.config_manager.save()

        return CommandResult(self.name, True, "; ".join(messages) if messages else "Settings updated.")
