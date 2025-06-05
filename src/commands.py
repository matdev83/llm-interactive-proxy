from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, List

from .proxy_logic import ProxyState


@dataclass
class CommandResult:
    name: str
    success: bool
    message: str


class BaseCommand:
    name: str

    def execute(self, args: Dict[str, Any], state: ProxyState) -> CommandResult:
        raise NotImplementedError


class SetCommand(BaseCommand):
    name = "set"

    def _parse_bool(self, value: str) -> bool | None:
        val = value.strip().lower()
        if val in ("true", "1", "yes", "on"):
            return True
        if val in ("false", "0", "no", "off", "none"):
            return False
        return None

    def execute(self, args: Dict[str, Any], state: ProxyState) -> CommandResult:
        messages: List[str] = []
        handled = False
        if isinstance(args.get("model"), str):
            model_val = args["model"].strip()
            if ":" not in model_val:
                return CommandResult(
                    self.name,
                    False,
                    "model must be specified as <backend>:<model>",
                )
            backend_part, model_name = model_val.split(":", 1)
            backend_part = backend_part.lower()

            try:
                from src import main as app_main
                backend_obj = getattr(app_main.app.state, f"{backend_part}_backend", None)
            except Exception:
                backend_obj = None

            available = (
                backend_obj.get_available_models() if backend_obj else []
            )

            if model_name in available:
                state.set_override_model(backend_part, model_name)
                handled = True
                messages.append(f"model set to {backend_part}:{model_name}")
            else:
                if state.interactive_mode:
                    return CommandResult(
                        self.name,
                        False,
                        f"model {backend_part}:{model_name} not available",
                    )
                state.set_override_model(backend_part, model_name, invalid=True)
                handled = True
        if isinstance(args.get("backend"), str):
            backend_val = args["backend"].strip().lower()
            try:
                from src import main as app_main
                functional = getattr(app_main.app.state, "functional_backends", {"openrouter", "gemini"})
            except Exception:
                functional = {"openrouter", "gemini"}

            if backend_val not in {"openrouter", "gemini"}:
                return CommandResult(
                    self.name,
                    False,
                    f"backend {backend_val} not supported",
                )
            if backend_val not in functional:
                return CommandResult(
                    self.name,
                    False,
                    f"backend {backend_val} not functional",
                )
            state.set_override_backend(backend_val)
            handled = True
            messages.append(f"backend set to {backend_val}")
        if isinstance(args.get("project"), str):
            state.set_project(args["project"])
            handled = True
            messages.append(f"project set to {args['project']}")
        for key in ("interactive", "interactive-mode"):
            if isinstance(args.get(key), str):
                val = self._parse_bool(args[key])
                if val is not None:
                    state.set_interactive_mode(val)
                    handled = True
                    messages.append(f"interactive mode set to {val}")
        if not handled:
            return CommandResult(self.name, False, "set: no valid parameters")
        return CommandResult(self.name, True, "; ".join(messages))


class UnsetCommand(BaseCommand):
    name = "unset"

    def execute(self, args: Dict[str, Any], state: ProxyState) -> CommandResult:
        messages: List[str] = []
        keys_to_unset = [k for k, v in args.items() if v is True]
        if "model" in keys_to_unset:
            state.unset_override_model()
            messages.append("model unset")
        if "backend" in keys_to_unset:
            state.unset_override_backend()
            messages.append("backend unset")
        if "project" in keys_to_unset:
            state.unset_project()
            messages.append("project unset")
        if any(k in keys_to_unset for k in ("interactive", "interactive-mode")):
            state.unset_interactive_mode()
            messages.append("interactive mode unset")
        if not keys_to_unset or not messages:
            return CommandResult(self.name, False, "unset: nothing to do")
        return CommandResult(self.name, True, "; ".join(messages))


class HelloCommand(BaseCommand):
    name = "hello"

    def execute(self, args: Dict[str, Any], state: ProxyState) -> CommandResult:
        state.hello_requested = True
        return CommandResult(self.name, True, "hello acknowledged")
