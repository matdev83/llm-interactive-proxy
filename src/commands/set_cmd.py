from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

from ..command_prefix import validate_command_prefix
from ..constants import SUPPORTED_BACKENDS
from .base import BaseCommand, CommandContext, CommandResult, register_command

if TYPE_CHECKING:
    pass  # No imports needed

logger = logging.getLogger(__name__)


@register_command
class SetCommand(BaseCommand):
    name = "set"
    format = "set(key=value, ...)"
    description = "Set session or global configuration values"
    examples = [
        "!/set(model=openrouter:gpt-4)",
        "!/set(interactive=true)",
        "!/set(reasoning-effort=high)",
        "!/set(reasoning=effort=medium)",
        "!/set(thinking-budget=2048)",
        "!/set(gemini-generation-config={'thinkingConfig': {'thinkingBudget': 1024}})",
        "!/set(temperature=0.7)",
        "!/set(openai_url=https://api.example.com/v1)",
        "!/set(loop-detection=true)",
        "!/set(tool-loop-detection=true)",
        "!/set(tool-loop-max-repeats=4)",
        "!/set(tool-loop-ttl=120)",
        "!/set(tool-loop-mode=break)",
    ]

    HandlerOutput = tuple[bool, str | CommandResult | None, bool]

    def __init__(
        self, app: FastAPI | None = None, functional_backends: set[str] | None = None
    ) -> None:
        super().__init__(app, functional_backends)

    def _parse_bool(self, value: str) -> bool | None:
        val = value.strip().lower()
        if val in ("true", "1", "yes", "on"):
            return True
        if val in ("false", "0", "no", "off", "none"):
            return False
        return None

    def _handle_backend_setting(
        self, args: Mapping[str, Any], state: Any
    ) -> HandlerOutput:
        backend_arg = args.get("backend")
        if not isinstance(backend_arg, str):
            return False, None, False

        backend_val = backend_arg.strip().lower()
        if backend_val not in SUPPORTED_BACKENDS:
            return (
                True,
                CommandResult(self.name, False, f"backend {backend_val} not supported"),
                False,
            )

        # Check against functional_backends ONLY if a list of functional_backends is provided
        if (
            self.functional_backends is not None
            and backend_val not in self.functional_backends
        ):
            state.unset_override_backend()
            return (
                True,
                f"backend {backend_val} not functional (session override unset)",
                False,
            )

        state.set_override_backend(backend_val)
        return True, f"backend set to {backend_val}", False

    def _handle_default_backend_setting(
        self, args: Mapping[str, Any], context: CommandContext | None = None
    ) -> HandlerOutput:
        backend_arg = args.get("default-backend")
        if not isinstance(backend_arg, str):
            return False, None, False

        backend_val = backend_arg.strip().lower()
        if backend_val not in SUPPORTED_BACKENDS:
            return (
                True,
                CommandResult(
                    self.name, False, f"default-backend {backend_val} not supported"
                ),
                False,
            )

        if (
            self.functional_backends is not None
            and backend_val not in self.functional_backends
        ):
            return (
                True,
                CommandResult(
                    self.name, False, f"default-backend {backend_val} not functional"
                ),
                False,
            )

        if context:
            context.backend_type = backend_val
        elif self.app:
            # Fallback to direct app access for backward compatibility
            self.app.state.backend_type = backend_val
            # Convert backend name to valid attribute name (replace hyphens with underscores)
            backend_attr = backend_val.replace("-", "_")
            self.app.state.backend = getattr(
                self.app.state, f"{backend_attr}_backend", self.app.state.backend
            )
        return True, f"default backend set to {backend_val}", True

    def _handle_model_setting(
        self,
        args: Mapping[str, Any],
        state: Any,
        backend_setting_failed_critically: bool,
        context: CommandContext | None = None,
    ) -> HandlerOutput:
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
            return (
                True,
                CommandResult(
                    self.name,
                    False,
                    "model must be specified as <backend>:<model> or <backend>/<model>",
                ),
                False,
            )
        backend_part = backend_part.lower()

        backend_obj = None
        if context:
            backend_obj = context.get_backend(backend_part)
        elif self.app:
            # Fallback to direct app access for backward compatibility
            # Convert backend name to valid attribute name (replace hyphens with underscores)
            backend_attr = backend_part.replace("-", "_")
            backend_obj = getattr(self.app.state, f"{backend_attr}_backend", None)

        if not backend_obj:
            return (
                True,
                CommandResult(
                    self.name,
                    False,
                    f"Backend '{backend_part}' for model not available/configured.",
                ),
                False,
            )

        available = backend_obj.get_available_models()
        if model_name in available:
            state.set_override_model(backend_part, model_name)
            return True, f"model set to {backend_part}:{model_name}", False
        elif state.interactive_mode:
            return (
                True,
                CommandResult(
                    self.name, False, f"model {backend_part}:{model_name} not available"
                ),
                False,
            )

        state.set_override_model(backend_part, model_name, invalid=True)
        return (
            True,
            f"model {backend_part}:{model_name} set (but may be invalid/unavailable)",
            False,
        )

    def _handle_project_setting(
        self, args: Mapping[str, Any], state: Any
    ) -> HandlerOutput:
        name_val_str: str | None = None
        key_used: str | None = None
        project_arg, pname_arg = args.get("project"), args.get("project-name")

        if isinstance(project_arg, str):
            name_val_str, key_used = project_arg, "project"
        elif isinstance(pname_arg, str):
            name_val_str, key_used = pname_arg, "project-name"
        else:
            return False, None, False

        state.set_project(name_val_str)
        return True, f"{key_used} set to {name_val_str}", False

    def _handle_project_dir_setting(
        self, args: Mapping[str, Any], state: Any
    ) -> HandlerOutput:
        dir_val_str: str | None = (
            args.get("project-dir") or args.get("dir") or args.get("project-directory")
        )
        if not isinstance(dir_val_str, str):
            return False, None, False

        import os

        if not os.path.isdir(dir_val_str):
            return (
                True,
                CommandResult(
                    self.name, False, f"Directory '{dir_val_str}' not found."
                ),
                False,
            )
        if not os.access(dir_val_str, os.R_OK):
            return (
                True,
                CommandResult(
                    self.name, False, f"Directory '{dir_val_str}' not readable."
                ),
                False,
            )

        state.set_project_dir(dir_val_str)
        return True, f"project-dir set to {dir_val_str}", False

    def _handle_interactive_mode_setting(
        self, args: Mapping[str, Any], state: Any
    ) -> HandlerOutput:
        val_str: str | None = None
        key_used: str | None = None
        inter_arg, inter_mode_arg = args.get("interactive"), args.get(
            "interactive-mode"
        )

        if isinstance(inter_arg, str):
            val_str, key_used = inter_arg, "interactive"
        elif isinstance(inter_mode_arg, str):
            val_str, key_used = inter_mode_arg, "interactive-mode"
        else:
            return False, None, False

        val = self._parse_bool(val_str)
        if val is None:
            return (
                True,
                CommandResult(
                    self.name, False, f"Invalid boolean value for {key_used}: {val_str}"
                ),
                False,
            )

        state.set_interactive_mode(val)
        return True, f"{key_used} set to {val}", True

    def _handle_api_key_redaction_setting(
        self, args: Mapping[str, Any], context: CommandContext | None = None
    ) -> HandlerOutput:
        key = "redact-api-keys-in-prompts"
        val_arg = args.get(key)
        if not isinstance(val_arg, str):
            return False, None, False

        val = self._parse_bool(val_arg)
        if val is None:
            return (
                True,
                CommandResult(
                    self.name, False, f"Invalid boolean value for {key}: {val_arg}"
                ),
                False,
            )

        if context:
            context.api_key_redaction_enabled = val
        elif self.app:
            # Fallback to direct app access for backward compatibility
            self.app.state.api_key_redaction_enabled = val
        else:
            return False, None, False
        return True, f"{key} set to {val}", True

    def _handle_command_prefix_setting(
        self, args: Mapping[str, Any], context: CommandContext | None = None
    ) -> HandlerOutput:
        key = "command-prefix"
        val_arg = args.get(key)
        if not isinstance(val_arg, str):
            return False, None, False

        error = validate_command_prefix(val_arg)
        if error:
            return True, CommandResult(self.name, False, error), False

        if context:
            context.command_prefix = val_arg
        elif self.app:
            # Fallback to direct app access for backward compatibility
            self.app.state.command_prefix = val_arg
        else:
            return False, None, False
        return True, f"{key} set to {val_arg}", True

    def _handle_reasoning_effort_setting(
        self, args: Mapping[str, Any], state: Any
    ) -> HandlerOutput:
        key = "reasoning-effort"
        val_arg = args.get(key)
        if not isinstance(val_arg, str):
            return False, None, False

        val = val_arg.strip().lower()
        if val not in {"low", "medium", "high"}:
            return (
                True,
                CommandResult(
                    self.name,
                    False,
                    f"reasoning-effort must be 'low', 'medium', or 'high', got: {val_arg}",
                ),
                False,
            )

        state.set_reasoning_effort(val)
        return True, f"{key} set to {val}", False

    def _handle_reasoning_config_setting(
        self, args: Mapping[str, Any], state: Any
    ) -> HandlerOutput:
        key = "reasoning"
        val_arg = args.get(key)
        if not isinstance(val_arg, dict | str):
            return False, None, False

        if isinstance(val_arg, str):
            # Simple string format like "effort=high" or "max_tokens=2000"
            try:
                if "=" in val_arg:
                    k, v = val_arg.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    if k == "effort" and v in {"low", "medium", "high"}:
                        config = {"effort": v}
                    elif k == "max_tokens" and v.isdigit():
                        config = {"max_tokens": str(int(v))}
                    elif k == "exclude" and v.lower() in {"true", "false"}:
                        config = {"exclude": str(v.lower() == "true")}
                    else:
                        return (
                            True,
                            CommandResult(
                                self.name,
                                False,
                                f"Invalid reasoning parameter: {k}={v}",
                            ),
                            False,
                        )
                else:
                    return (
                        True,
                        CommandResult(
                            self.name,
                            False,
                            "Invalid reasoning format. Use key=value or dict format",
                        ),
                        False,
                    )
            except ValueError:
                return (
                    True,
                    CommandResult(
                        self.name, False, f"Invalid reasoning format: {val_arg}"
                    ),
                    False,
                )
        else:
            # Dict format
            config = val_arg

        state.set_reasoning_config(config)
        return True, f"{key} set to {config}", False

    def _handle_thinking_budget_setting(
        self, args: Mapping[str, Any], state: Any
    ) -> HandlerOutput:
        key = "thinking-budget"
        val_arg = args.get(key)
        if val_arg is None:
            return False, None, False

        try:
            budget = int(val_arg)
            if budget < 128 or budget > 32768:
                return (
                    True,
                    CommandResult(
                        self.name,
                        False,
                        f"thinking-budget must be between 128 and 32768, got: {budget}",
                    ),
                    False,
                )

            state.set_thinking_budget(budget)
            return True, f"{key} set to {budget}", False
        except (ValueError, TypeError):
            return (
                True,
                CommandResult(
                    self.name,
                    False,
                    f"thinking-budget must be a valid integer, got: {val_arg}",
                ),
                False,
            )

    def _handle_gemini_generation_config_setting(
        self, args: Mapping[str, Any], state: Any
    ) -> HandlerOutput:
        key = "gemini-generation-config"
        val_arg = args.get(key)
        if not isinstance(val_arg, dict | str):
            return False, None, False

        if isinstance(val_arg, str):
            try:
                config = json.loads(val_arg)
            except json.JSONDecodeError:
                return False, f"Invalid JSON format for {key}: {val_arg}", True
        else:
            config = val_arg

        if not isinstance(config, dict):
            return False, f"Invalid format for {key}, expected dict", True

        try:
            state.set_gemini_generation_config(config)
            return True, f"gemini generation config set to: {config}", False
        except Exception as e:
            return False, f"Failed to set {key}: {e!s}", True

    def _handle_temperature_setting(
        self, args: Mapping[str, Any], state: Any
    ) -> HandlerOutput:
        key = "temperature"
        val_arg = args.get(key)
        if val_arg is None:
            return False, None, False

        try:
            # Convert to float
            if isinstance(val_arg, str | int | float):
                temperature = float(val_arg)
            else:
                return (
                    True,
                    CommandResult(
                        self.name, False, f"Invalid temperature format: {val_arg}"
                    ),
                    False,
                )

            state.set_temperature(temperature)
            return True, f"temperature set to: {temperature}", False
        except ValueError as e:
            # Handle specific ValueError from set_temperature validation
            if "Temperature must be between 0.0 and 2.0" in str(e):
                return True, CommandResult(self.name, False, str(e)), False
            else:
                return (
                    True,
                    CommandResult(
                        self.name, False, f"Invalid temperature value: {val_arg}"
                    ),
                    False,
                )
        except Exception as e:
            return True, CommandResult(self.name, False, str(e)), False

    def _handle_openai_url_setting(
        self, args: Mapping[str, Any], state: Any
    ) -> HandlerOutput:
        key = "openai_url"
        val_arg = args.get(key)
        if not isinstance(val_arg, str):
            return False, None, False

        try:
            state.set_openai_url(val_arg)
            return True, f"OpenAI URL set to: {val_arg}", False
        except ValueError as e:
            return True, CommandResult(self.name, False, str(e)), False
        except Exception as e:
            return (
                True,
                CommandResult(self.name, False, f"Failed to set OpenAI URL: {e!s}"),
                False,
            )

    def _save_config_if_needed(
        self,
        any_persistent_change: bool,
        messages: list[str],
        context: CommandContext | None = None,
    ) -> None:
        if not any_persistent_change:
            return

        if context:
            try:
                context.save_config()
            except Exception as e:
                logger.error(f"Failed to save configuration: {e}")
                messages.append("(Warning: configuration not saved)")
        elif self.app and hasattr(self.app.state, "config_manager"):
            # Fallback to direct app access for backward compatibility
            config_manager = getattr(self.app.state, "config_manager", None)
            if config_manager:
                try:
                    config_manager.save()
                except Exception as e:
                    logger.error(f"Failed to save configuration: {e}")
                    messages.append("(Warning: configuration not saved)")
            else:
                logger.warning("Config manager was None, not saving.")

    def _get_handler_tasks(
        self,
        args: Mapping[str, Any],
        state: Any,
        backend_setting_failed_critically: bool,
        context: CommandContext | None = None,
    ) -> list[Callable[[], HandlerOutput]]:
        """Get the list of handler tasks for processing arguments."""
        return [
            lambda: self._handle_backend_setting(args, state),
            lambda: self._handle_default_backend_setting(args, context),
            lambda: self._handle_model_setting(
                args, state, backend_setting_failed_critically, context
            ),
            lambda: self._handle_project_setting(args, state),
            lambda: self._handle_project_dir_setting(args, state),
            lambda: self._handle_interactive_mode_setting(args, state),
            lambda: self._handle_api_key_redaction_setting(args, context),
            lambda: self._handle_command_prefix_setting(args, context),
            lambda: self._handle_reasoning_effort_setting(args, state),
            lambda: self._handle_reasoning_config_setting(args, state),
            lambda: self._handle_thinking_budget_setting(args, state),
            lambda: self._handle_gemini_generation_config_setting(args, state),
            lambda: self._handle_temperature_setting(args, state),
            lambda: self._handle_openai_url_setting(args, state),
            lambda: self._handle_loop_detection_setting(args, state),
            lambda: self._handle_tool_loop_detection_setting(args, state),
            lambda: self._handle_tool_loop_max_repeats_setting(args, state),
            lambda: self._handle_tool_loop_ttl_seconds_setting(args, state),
            lambda: self._handle_tool_loop_mode_setting(args, state),
        ]

    def _handle_loop_detection_setting(
        self, args: Mapping[str, Any], state: Any
    ) -> HandlerOutput:
        key_variants = ["loop-detection", "loop_detection", "loop"]
        val_arg: str | None = None
        used_key: str | None = None
        for k in key_variants:
            v = args.get(k)
            if isinstance(v, str):
                val_arg = v
                used_key = k
                break
        if val_arg is None:
            return False, None, False

        val = self._parse_bool(val_arg)
        if val is None:
            return (
                True,
                CommandResult(
                    self.name, False, f"Invalid boolean for {used_key}: {val_arg}"
                ),
                False,
            )

        state.set_loop_detection_enabled(val)
        return True, f"{used_key} set to {val}", False

    def _handle_tool_loop_detection_setting(
        self, args: Mapping[str, Any], state: Any
    ) -> HandlerOutput:
        key_variants = ["tool-loop-detection", "tool_loop_detection", "tool-loop"]
        val_arg: str | None = None
        used_key: str | None = None
        for k in key_variants:
            v = args.get(k)
            if isinstance(v, str):
                val_arg = v
                used_key = k
                break
        if val_arg is None:
            return False, None, False

        val = self._parse_bool(val_arg)
        if val is None:
            return (
                True,
                CommandResult(
                    self.name, False, f"Invalid boolean for {used_key}: {val_arg}"
                ),
                False,
            )

        state.set_tool_loop_detection_enabled(val)
        return True, f"{used_key} set to {val}", False

    def _handle_tool_loop_max_repeats_setting(
        self, args: Mapping[str, Any], state: Any
    ) -> HandlerOutput:
        key_variants = [
            "tool-loop-max-repeats",
            "tool_loop_max_repeats",
            "tool-loop-repeats",
        ]
        val_arg = None
        used_key = None
        for k in key_variants:
            v = args.get(k)
            if v is not None:
                val_arg = v
                used_key = k
                break
        if val_arg is None:
            return False, None, False

        try:
            max_repeats = int(val_arg)
            state.set_tool_loop_max_repeats(max_repeats)
            return True, f"{used_key} set to {max_repeats}", False
        except ValueError as e:
            if "must be at least 2" in str(e):
                return True, CommandResult(self.name, False, str(e)), False
            else:
                return (
                    True,
                    CommandResult(
                        self.name,
                        False,
                        f"Invalid integer value for {used_key}: {val_arg}",
                    ),
                    False,
                )
        except Exception as e:
            return True, CommandResult(self.name, False, str(e)), False

    def _handle_tool_loop_ttl_seconds_setting(
        self, args: Mapping[str, Any], state: Any
    ) -> HandlerOutput:
        key_variants = [
            "tool-loop-ttl-seconds",
            "tool_loop_ttl_seconds",
            "tool-loop-ttl",
        ]
        val_arg = None
        used_key = None
        for k in key_variants:
            v = args.get(k)
            if v is not None:
                val_arg = v
                used_key = k
                break
        if val_arg is None:
            return False, None, False

        try:
            ttl_seconds = int(val_arg)
            state.set_tool_loop_ttl_seconds(ttl_seconds)
            return True, f"{used_key} set to {ttl_seconds}", False
        except ValueError as e:
            if "must be positive" in str(e):
                return True, CommandResult(self.name, False, str(e)), False
            else:
                return (
                    True,
                    CommandResult(
                        self.name,
                        False,
                        f"Invalid integer value for {used_key}: {val_arg}",
                    ),
                    False,
                )
        except Exception as e:
            return True, CommandResult(self.name, False, str(e)), False

    def _handle_tool_loop_mode_setting(
        self, args: Mapping[str, Any], state: Any
    ) -> HandlerOutput:
        key_variants = ["tool-loop-mode", "tool_loop_mode"]
        val_arg: str | None = None
        used_key: str | None = None
        for k in key_variants:
            v = args.get(k)
            if isinstance(v, str):
                val_arg = v
                used_key = k
                break
        if val_arg is None:
            return False, None, False

        try:
            mode = val_arg.strip().lower()
            # Handle shorthand "chance" for "chance_then_break"
            if mode == "chance":
                mode = "chance_then_break"

            state.set_tool_loop_mode(mode)
            return True, f"{used_key} set to {mode}", False
        except ValueError as e:
            return True, CommandResult(self.name, False, str(e)), False
        except Exception as e:
            return True, CommandResult(self.name, False, str(e)), False

    def _process_handler_tasks(
        self, tasks: list[Callable[[], HandlerOutput]]
    ) -> tuple[bool, list[str], bool, bool]:
        """Process handler tasks and return results."""
        messages: list[str] = []
        any_handled = False
        any_persistent_change = False
        backend_setting_failed_critically = False

        for i, task_func in enumerate(tasks):
            handled, result, persistent = task_func()
            if not handled:
                continue

            any_handled = True
            if isinstance(result, CommandResult):
                # Early return for command result errors
                raise ValueError(result)
            if isinstance(result, str):
                messages.append(result)
                if i == 0 and "not functional" in result:
                    backend_setting_failed_critically = True
            if persistent:
                any_persistent_change = True

        return (
            any_handled,
            messages,
            any_persistent_change,
            backend_setting_failed_critically,
        )

    def execute(self, args: Mapping[str, Any], state: Any) -> CommandResult:
        """Execute the set command with the provided arguments."""
        logger.debug(f"SetCommand.execute called with args: {args}")

        try:
            backend_setting_failed_critically = False
            tasks = self._get_handler_tasks(
                args, state, backend_setting_failed_critically
            )
            any_handled, messages, any_persistent_change, _ = (
                self._process_handler_tasks(tasks)
            )

            if not any_handled:
                return CommandResult(
                    self.name,
                    False,
                    "set: no valid parameters provided or action taken",
                )

            self._save_config_if_needed(any_persistent_change, messages)

            final_message = "; ".join(filter(None, messages))
            return CommandResult(
                self.name,
                True,
                final_message if final_message else "Settings processed.",
            )

        except ValueError as e:
            # Handle early return command results
            if isinstance(e.args[0], CommandResult):
                return e.args[0]
            raise

    def execute_with_context(
        self,
        args: Mapping[str, Any],
        state: Any,
        context: CommandContext | None = None,
    ) -> CommandResult:
        """Execute command with context for better decoupling."""
        logger.debug(f"SetCommand.execute_with_context called with args: {args}")

        try:
            backend_setting_failed_critically = False
            tasks = self._get_handler_tasks(
                args, state, backend_setting_failed_critically, context
            )
            any_handled, messages, any_persistent_change, _ = (
                self._process_handler_tasks(tasks)
            )

            if not any_handled:
                return CommandResult(
                    self.name,
                    False,
                    "set: no valid parameters provided or action taken",
                )

            self._save_config_if_needed(any_persistent_change, messages, context)

            final_message = "; ".join(filter(None, messages))
            return CommandResult(
                self.name,
                True,
                final_message if final_message else "Settings processed.",
            )

        except ValueError as e:
            # Handle early return command results
            if isinstance(e.args[0], CommandResult):
                return e.args[0]
            raise
