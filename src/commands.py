from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, List

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .proxy_logic import ProxyState


@dataclass
class CommandResult:
    name: str
    success: bool
    message: str


class BaseCommand:
    name: str

    def execute(self, args: Dict[str, Any], state: 'ProxyState') -> CommandResult:
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

    def execute(self, args: Dict[str, Any], state: 'ProxyState') -> CommandResult:
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

    def execute(self, args: Dict[str, Any], state: 'ProxyState') -> CommandResult:
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

    def execute(self, args: Dict[str, Any], state: 'ProxyState') -> CommandResult:
        state.hello_requested = True
        return CommandResult(self.name, True, "hello acknowledged")


class _FailoverBase(BaseCommand):
    def _ensure_interactive(self, state: 'ProxyState', messages: List[str]) -> None:
        if not state.interactive_mode:
            state.set_interactive_mode(True)
            messages.append("This llm-interactive-proxy session is now set to interactive mode")


class CreateFailoverRouteCommand(_FailoverBase):
    name = "create-failover-route"

    def execute(self, args: Dict[str, Any], state: 'ProxyState') -> CommandResult:
        msgs: List[str] = []
        self._ensure_interactive(state, msgs)
        name = args.get("name")
        policy = str(args.get("policy", "")).lower()
        if not name or policy not in {"k", "m", "km", "mk"}:
            return CommandResult(self.name, False, "create-failover-route requires name and valid policy")
        state.create_failover_route(name, policy)
        msgs.append(f"failover route {name} created with policy {policy}")
        return CommandResult(self.name, True, "; ".join(msgs))


class RouteAppendCommand(_FailoverBase):
    name = "route-append"

    def execute(self, args: Dict[str, Any], state: 'ProxyState') -> CommandResult:
        msgs: List[str] = []
        self._ensure_interactive(state, msgs)
        name = args.get("name")
        if not name or name not in state.failover_routes:
            return CommandResult(self.name, False, f"route {name} not found")
        elements = [k for k in args.keys() if k != "name"]
        if not elements:
            return CommandResult(self.name, False, "no route elements specified")
        for e in elements:
            if ":" not in e:
                continue
            state.append_route_element(name, e)
        msgs.append(f"elements appended to {name}")
        return CommandResult(self.name, True, "; ".join(msgs))


class RoutePrependCommand(_FailoverBase):
    name = "route-prepend"

    def execute(self, args: Dict[str, Any], state: 'ProxyState') -> CommandResult:
        msgs: List[str] = []
        self._ensure_interactive(state, msgs)
        name = args.get("name")
        if not name or name not in state.failover_routes:
            return CommandResult(self.name, False, f"route {name} not found")
        elements = [k for k in args.keys() if k != "name"]
        if not elements:
            return CommandResult(self.name, False, "no route elements specified")
        for e in reversed(elements):
            if ":" not in e:
                continue
            state.prepend_route_element(name, e)
        msgs.append(f"elements prepended to {name}")
        return CommandResult(self.name, True, "; ".join(msgs))


class DeleteFailoverRouteCommand(_FailoverBase):
    name = "delete-failover-route"

    def execute(self, args: Dict[str, Any], state: 'ProxyState') -> CommandResult:
        msgs: List[str] = []
        self._ensure_interactive(state, msgs)
        name = args.get("name")
        if not name or name not in state.failover_routes:
            return CommandResult(self.name, False, f"route {name} not found")
        state.delete_failover_route(name)
        msgs.append(f"failover route {name} deleted")
        return CommandResult(self.name, True, "; ".join(msgs))


class RouteClearCommand(_FailoverBase):
    name = "route-clear"

    def execute(self, args: Dict[str, Any], state: 'ProxyState') -> CommandResult:
        msgs: List[str] = []
        self._ensure_interactive(state, msgs)
        name = args.get("name")
        if not name or name not in state.failover_routes:
            return CommandResult(self.name, False, f"route {name} not found")
        state.clear_route(name)
        msgs.append(f"route {name} cleared")
        return CommandResult(self.name, True, "; ".join(msgs))


class ListFailoverRoutesCommand(_FailoverBase):
    name = "list-failover-routes"

    def execute(self, args: Dict[str, Any], state: 'ProxyState') -> CommandResult:
        msgs: List[str] = []
        self._ensure_interactive(state, msgs)
        data = state.list_routes()
        if not data:
            msgs.append("no failover routes defined")
        else:
            msgs.append(", ".join(f"{n}:{p}" for n, p in data.items()))
        return CommandResult(self.name, True, "; ".join(msgs))


class RouteListCommand(_FailoverBase):
    name = "route-list"

    def execute(self, args: Dict[str, Any], state: ProxyState) -> CommandResult:
        msgs: List[str] = []
        self._ensure_interactive(state, msgs)
        name = args.get("name")
        if not name or name not in state.failover_routes:
            return CommandResult(self.name, False, f"route {name} not found")
        elems = state.list_route(name)
        msgs.append(", ".join(elems) if elems else "<empty>")
        return CommandResult(self.name, True, "; ".join(msgs))
