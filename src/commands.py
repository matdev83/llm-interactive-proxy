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
            state.set_override_model(args["model"])
            handled = True
            messages.append(f"model set to {args['model']}")
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
