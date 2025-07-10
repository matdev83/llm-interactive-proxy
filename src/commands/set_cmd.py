from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Set, Tuple, Optional, Union, Callable

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

    HandlerOutput = Tuple[bool, Union[str, CommandResult, None], bool]

    def __init__(self, app: FastAPI | None = None,
                 functional_backends: Set[str] | None = None) -> None:
        super().__init__(app, functional_backends)

    def _parse_bool(self, value: str) -> bool | None:
        val = value.strip().lower()
        if val in ("true", "1", "yes", "on"): return True
        if val in ("false", "0", "no", "off", "none"): return False
        return None

    def _handle_backend_setting(self, args: Dict[str, Any], state: "ProxyState") -> HandlerOutput:
        backend_arg = args.get("backend")
        if not isinstance(backend_arg, str):
            return False, None, False

        backend_val = backend_arg.strip().lower()
        if backend_val not in {"openrouter", "gemini", "gemini-cli-direct"}:
            return True, CommandResult(self.name, False, f"backend {backend_val} not supported"), False

        # Check against functional_backends ONLY if a list of functional_backends is provided
        if self.functional_backends is not None and backend_val not in self.functional_backends:
            state.unset_override_backend()
            return True, f"backend {backend_val} not functional (session override unset)", False

        state.set_override_backend(backend_val)
        return True, f"backend set to {backend_val}", False

    def _handle_default_backend_setting(self, args: Dict[str, Any]) -> HandlerOutput:
        backend_arg = args.get("default-backend")
        if not isinstance(backend_arg, str):
            return False, None, False

        backend_val = backend_arg.strip().lower()
        if backend_val not in {"openrouter", "gemini", "gemini-cli-direct"}:
            return True, CommandResult(self.name, False, f"default-backend {backend_val} not supported"), False

        if self.functional_backends is not None and backend_val not in self.functional_backends:
            return True, CommandResult(self.name, False, f"default-backend {backend_val} not functional"), False

        if self.app:
            self.app.state.backend_type = backend_val
            self.app.state.backend = getattr(self.app.state, f"{backend_val}_backend", self.app.state.backend)
        return True, f"default backend set to {backend_val}", True

    def _handle_model_setting(self, args: Dict[str, Any], state: "ProxyState", backend_setting_failed_critically: bool) -> HandlerOutput:
        model_arg = args.get("model")
        if not isinstance(model_arg, str):
            return False, None, False

        if backend_setting_failed_critically:
            return True, "model not set due to prior backend issue", False

        model_val = model_arg.strip()
        
        # Use robust parsing that handles both slash and colon syntax
        from src.models import parse_model_backend
        backend_part, model_name = parse_model_backend(model_val)
        if not backend_part:
            return True, CommandResult(self.name, False, "model must be specified as <backend>:<model> or <backend>/<model>"), False
        backend_part = backend_part.lower()

        backend_obj = getattr(self.app.state, f"{backend_part}_backend", None) if self.app else None
        if not backend_obj:
             return True, CommandResult(self.name, False, f"Backend '{backend_part}' for model not available/configured."), False

        available = backend_obj.get_available_models()
        if model_name in available:
            state.set_override_model(backend_part, model_name)
            return True, f"model set to {backend_part}:{model_name}", False
        elif state.interactive_mode:
            return True, CommandResult(self.name, False, f"model {backend_part}:{model_name} not available"), False

        state.set_override_model(backend_part, model_name, invalid=True)
        return True, f"model {backend_part}:{model_name} set (but may be invalid/unavailable)", False

    def _handle_project_setting(self, args: Dict[str, Any], state: "ProxyState") -> HandlerOutput:
        name_val_str: Optional[str] = None
        key_used: Optional[str] = None
        project_arg, pname_arg = args.get("project"), args.get("project-name")

        if isinstance(project_arg, str): name_val_str, key_used = project_arg, "project"
        elif isinstance(pname_arg, str): name_val_str, key_used = pname_arg, "project-name"
        else: return False, None, False

        state.set_project(name_val_str)
        return True, f"{key_used} set to {name_val_str}", False

    def _handle_interactive_mode_setting(self, args: Dict[str, Any], state: "ProxyState") -> HandlerOutput:
        val_str: Optional[str] = None
        key_used: Optional[str] = None
        inter_arg, inter_mode_arg = args.get("interactive"), args.get("interactive-mode")

        if isinstance(inter_arg, str): val_str, key_used = inter_arg, "interactive"
        elif isinstance(inter_mode_arg, str): val_str, key_used = inter_mode_arg, "interactive-mode"
        else: return False, None, False

        val = self._parse_bool(val_str)
        if val is None:
            return True, CommandResult(self.name, False, f"Invalid boolean value for {key_used}: {val_str}"), False

        state.set_interactive_mode(val)
        return True, f"{key_used} set to {val}", True

    def _handle_api_key_redaction_setting(self, args: Dict[str, Any]) -> HandlerOutput:
        key = "redact-api-keys-in-prompts"
        val_arg = args.get(key)
        if not isinstance(val_arg, str) or not self.app:
            return False, None, False

        val = self._parse_bool(val_arg)
        if val is None:
            return True, CommandResult(self.name, False, f"Invalid boolean value for {key}: {val_arg}"), False

        self.app.state.api_key_redaction_enabled = val
        return True, f"{key} set to {val}", True

    def _handle_command_prefix_setting(self, args: Dict[str, Any]) -> HandlerOutput:
        key = "command-prefix"
        val_arg = args.get(key)
        if not isinstance(val_arg, str) or not self.app:
            return False, None, False

        error = validate_command_prefix(val_arg)
        if error: return True, CommandResult(self.name, False, error), False

        self.app.state.command_prefix = val_arg
        return True, f"{key} set to {val_arg}", True

    def _save_config_if_needed(self, any_persistent_change: bool, messages: List[str]) -> None:
        if not any_persistent_change or not self.app or not hasattr(self.app.state, "config_manager"):
            return

        config_manager = getattr(self.app.state, "config_manager", None)
        if config_manager: # Simplified check
            try:
                config_manager.save()
            except Exception as e:
                logger.error(f"Failed to save configuration: {e}")
                messages.append("(Warning: configuration not saved)")
        else:
            logger.warning("Config manager was None, not saving.") # Slightly different log

    def execute(self, args: Dict[str, Any], state: "ProxyState") -> CommandResult:
        logger.debug(f"SetCommand.execute called with args: {args}")
        messages: List[str] = []
        any_handled = False
        any_persistent_change = False
        backend_setting_failed_critically = False

        tasks: List[Callable[[], SetCommand.HandlerOutput]] = [
            lambda: self._handle_backend_setting(args, state),
            lambda: self._handle_default_backend_setting(args),
            lambda: self._handle_model_setting(args, state, backend_setting_failed_critically),
            lambda: self._handle_project_setting(args, state),
            lambda: self._handle_interactive_mode_setting(args, state),
            lambda: self._handle_api_key_redaction_setting(args),
            lambda: self._handle_command_prefix_setting(args),
        ]

        for i, task_func in enumerate(tasks):
            handled, result, persistent = task_func()
            if not handled:
                continue

            any_handled = True
            if isinstance(result, CommandResult): return result
            if isinstance(result, str):
                messages.append(result)
                if i == 0 and "not functional" in result:
                    backend_setting_failed_critically = True
            if persistent:
                any_persistent_change = True

        if not any_handled:
            return CommandResult(self.name, False, "set: no valid parameters provided or action taken")

        self._save_config_if_needed(any_persistent_change, messages)

        final_message = "; ".join(filter(None, messages))
        return CommandResult(self.name, True, final_message if final_message else "Settings processed.")
