from __future__ import annotations

from typing import Dict, Any, List, Set, Callable # Added Callable

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
                return True, CommandResult(self.name, False, f"backend {backend_val} not functional") # Indicates it was handled, but resulted in a "not functional" state.
            state.set_override_backend(backend_val)
            messages.append(f"backend set to {backend_val}")
            return True, None # Successfully set and functional
        return False, None # Not handled (key not present or not a string) or no failure if key not 'backend'

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


    def _handle_project_setting(self, args: Dict[str, Any], state: "ProxyState", messages: List[str]) -> tuple[bool, bool, CommandResult | None]:
        """Handles 'project' or 'project-name' setting. Returns (handled, persistent_change, error_result)."""
        project_arg = args.get("project") or args.get("project-name")
        if isinstance(project_arg, str):
            name_val = project_arg.strip()
            state.set_project(name_val)
            messages.append(f"project set to {name_val}")
            return True, False, None # handled, not persistent for config saving, no error
        return False, False, None

    def _handle_interactive_mode_setting(self, args: Dict[str, Any], state: "ProxyState", messages: List[str]) -> tuple[bool, bool, CommandResult | None]:
        """Handles 'interactive' or 'interactive-mode' setting. Returns (handled, persistent_change, error_result)."""
        for key in ("interactive", "interactive-mode"):
            if isinstance(args.get(key), str):
                val = self._parse_bool(args[key])
                if val is not None:
                    state.set_interactive_mode(val)
                    messages.append(f"interactive mode set to {val}")
                    return True, True, None # handled, persistent_change, no error
        return False, False, None

    def _handle_redact_api_keys_setting(self, args: Dict[str, Any], messages: List[str]) -> tuple[bool, bool, CommandResult | None]:
        """Handles 'redact-api-keys-in-prompts'. Returns (handled, persistent_change, error_result)."""
        if isinstance(args.get("redact-api-keys-in-prompts"), str) and self.app is not None:
            val = self._parse_bool(args["redact-api-keys-in-prompts"])
            if val is not None:
                self.app.state.api_key_redaction_enabled = val
                messages.append(f"API key redaction in prompts set to {val}")
                return True, True, None # handled, persistent_change, no error
        return False, False, None

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

    # Type alias for handler functions
    # Handler returns: (key_was_present_and_handled, persistent_change, error_result_or_none)
    # The 'backend_set_failed' is passed as a mutable list of one boolean to allow modification by the handler.
    GeneralSettingHandler = Callable[[Dict[str, Any], "ProxyState", List[str], List[bool]], tuple[bool, bool, CommandResult | None]]

    def _backend_setting_handler(self, args: Dict[str, Any], state: "ProxyState", messages: List[str], backend_set_failed_ref: List[bool]) -> tuple[bool, bool, CommandResult | None]:
        if "backend" not in args:
            return False, False, None
        handled, cmd_result = self._handle_backend_setting(args, state, messages)
        if cmd_result: # This implies a failure message
            backend_set_failed_ref[0] = True # Mark as failed if there's a command result
            return True, False, cmd_result # Handled (attempted), not persistent, error
        # If _handle_backend_setting returns (False, None), it means backend was valid but not functional (e.g. not in functional_backends)
        # If it returns (True, None) it means it was set.
        # The original logic: `backend_set_failed = not handled` (where handled was the first element of the tuple from _handle_backend_setting)
        # The `handled` from `_handle_backend_setting` means "backend was set successfully and is functional"
        # So, if `not handled` (from _handle_backend_setting), then backend_set_failed should be true.
        # The `_handle_backend_setting` returns (True, None) for success, (False, CommandResult) for "not supported", (True, CommandResult) for "not functional".
        # Let's adjust _handle_backend_setting's return for clarity or handle it here.
        # Current _handle_backend_setting:
        #   - Returns (False, CommandResult) if backend_val not supported.
        #   - Returns (True, CommandResult) if backend_val not functional. (Here, backend_set_failed should be true)
        #   - Returns (False, None) if successfully set. (This seems inverted, should be True, None for success)
        # Let's assume _handle_backend_setting: (success_flag, result_or_none)
        # If success_flag is False AND result_or_none is a CommandResult -> hard failure, return result
        # If success_flag is True AND result_or_none is a CommandResult -> soft failure (e.g. not functional), backend_set_failed = True
        # If success_flag is True AND result_or_none is None -> success, backend_set_failed = False
        #
        # Re-reading _handle_backend_setting:
        #   - `return False, CommandResult(self.name, False, f"backend {backend_val} not supported")` -> Error
        #   - `return True, CommandResult(self.name, False, f"backend {backend_val} not functional")` -> Error, backend_set_failed = True
        #   - `return False, None` -> Success. This is confusing. Let's make its first return True for success.
        # For now, I'll stick to the current _handle_backend_setting logic and derive backend_set_failed here.
        # If cmd_result is None, it means success.
        # Original: backend_set_failed, cmd_result = self._handle_backend_setting(args, state, messages)
        # if cmd_result: return cmd_result. `backend_set_failed` was the first item.
        # Let's simplify: _handle_backend_setting should return (CommandResult | None, was_functional_if_set_attempted)
        # No, let's just use the existing structure and set backend_set_failed based on cmd_result.
        # If cmd_result is not None, it's a failure of some sort.
        # If cmd_result is CommandResult with success=False, then backend_set_failed=True.
        if cmd_result is None: # Success
             backend_set_failed_ref[0] = False
        else: # Some error occurred
            backend_set_failed_ref[0] = True

        return True, False, cmd_result # Handled (attempted), not persistent, optional error

    def _default_backend_setting_handler(self, args: Dict[str, Any], _state: "ProxyState", messages: List[str], _bsf: List[bool]) -> tuple[bool, bool, CommandResult | None]:
        if "default-backend" not in args:
            return False, False, None
        persistent, cmd_result = self._handle_default_backend_setting(args, messages)
        return True, persistent, cmd_result # Handled (attempted), persistent flag from method, optional error

    def _model_setting_handler(self, args: Dict[str, Any], state: "ProxyState", messages: List[str], backend_set_failed_ref: List[bool]) -> tuple[bool, bool, CommandResult | None]:
        if "model" not in args:
            return False, False, None
        handled_model, cmd_result = self._handle_model_setting(args, state, messages, backend_set_failed_ref[0])
        return handled_model, False, cmd_result # Model is session-specific, not persistent

    def _project_setting_handler(self, args: Dict[str, Any], state: "ProxyState", messages: List[str], _bsf: List[bool]) -> tuple[bool, bool, CommandResult | None]:
        if not (args.get("project") or args.get("project-name")):
            return False, False, None
        return self._handle_project_setting(args, state, messages)

    def _interactive_mode_setting_handler(self, args: Dict[str, Any], state: "ProxyState", messages: List[str], _bsf: List[bool]) -> tuple[bool, bool, CommandResult | None]:
        if not (args.get("interactive") or args.get("interactive-mode")):
            return False, False, None
        return self._handle_interactive_mode_setting(args, state, messages)

    def _redact_api_keys_setting_handler(self, args: Dict[str, Any], _state: "ProxyState", messages: List[str], _bsf: List[bool]) -> tuple[bool, bool, CommandResult | None]:
        if "redact-api-keys-in-prompts" not in args:
            return False, False, None
        # Adapt NoState to GeneralSettingHandler signature
        return self._handle_redact_api_keys_setting(args, messages)

    def _command_prefix_setting_handler(self, args: Dict[str, Any], _state: "ProxyState", messages: List[str], _bsf: List[bool]) -> tuple[bool, bool, CommandResult | None]:
        if "command-prefix" not in args:
            return False, False, None
        # Adapt NoState to GeneralSettingHandler signature
        return self._handle_command_prefix_setting(args, messages)


    def execute(self, args: Dict[str, Any], state: "ProxyState") -> CommandResult:
        messages: List[str] = []
        any_arg_processed = False # Tracks if any argument key led to a handler being called
        persistent_change_made = False
        backend_set_failed_ref = [False] # Use a list to pass by reference

        # Order matters: backend -> default-backend -> model -> others
        # Each handler now takes `backend_set_failed_ref`
        setting_handlers: List[self.GeneralSettingHandler] = [
            self._backend_setting_handler,
            self._default_backend_setting_handler,
            self._model_setting_handler,
            self._project_setting_handler,
            self._interactive_mode_setting_handler,
            self._redact_api_keys_setting_handler,
            self._command_prefix_setting_handler,
        ]

        for handler_method in setting_handlers:
            # The handler itself will check if its relevant key(s) are in args
            # This allows handlers to manage aliases like "project" and "project-name"
            key_present_and_handled, persistent_current, cmd_result = handler_method(args, state, messages, backend_set_failed_ref)

            if cmd_result: # An error occurred and was returned by the handler
                return cmd_result

            if key_present_and_handled:
                any_arg_processed = True # Mark that at least one arg group was processed
                if persistent_current:
                    persistent_change_made = True

        # Check if any arg in the original args dict was actually processed by a handler.
        # This is a bit tricky because handlers now self-determine if they should run.
        # A simpler check: if messages list is empty AND no persistent change AND no specific early exit,
        # it might mean no known args were provided.
        # The any_arg_processed flag should correctly capture if any handler found its key.

        if not any_arg_processed and args: # args is not empty, but nothing was handled
             # This condition means that 'args' contained keys, but none of them were recognized by any handlers.
             # We need to ensure that if args is empty, we don't show this.
             # The previous `if not any_handled:` was based on `args.get("key") is not None` checks.
             # Now, `any_arg_processed` is more accurate.
            return CommandResult(self.name, False, "set: no valid or recognized parameters provided")

        if persistent_change_made and self.app is not None and hasattr(self.app.state, "config_manager") and self.app.state.config_manager:
            self.app.state.config_manager.save()

        return CommandResult(self.name, True, "; ".join(messages) if messages else "Settings updated.")
