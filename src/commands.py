from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any, List, Set

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

    def execute(self, args: Dict[str, Any], state: "ProxyState") -> CommandResult:
        raise NotImplementedError


from fastapi import FastAPI


class SetCommand(BaseCommand):
    name = "set"

    def __init__(self, app: FastAPI, functional_backends: Set[str] | None = None):
        self.app = app
        self.functional_backends = functional_backends or set()

    def _parse_bool(self, value: str) -> bool | None:
        val = value.strip().lower()
        if val in ("true", "1", "yes", "on"):
            return True
        if val in ("false", "0", "no", "off", "none"):
            return False
        return None

    def execute(self, args: Dict[str, Any], state: "ProxyState") -> CommandResult:
        messages: List[str] = []
        handled = False
        backend_set_failed = False
        # Backend set logic first, so we can skip model set if backend is not functional
        if isinstance(args.get("backend"), str):
            backend_val = args["backend"].strip().lower()

            if backend_val not in {"openrouter", "gemini"}:
                return CommandResult(
                    self.name,
                    False,
                    f"backend {backend_val} not supported",
                )

            if backend_val not in self.functional_backends:
                # Do NOT set override_backend if not functional
                state.unset_override_backend()  # Ensure it's unset if it was previously set
                backend_set_failed = True
                return CommandResult(
                    self.name,
                    False,
                    f"backend {backend_val} not functional",
                )

            # Only set override_backend if functional and supported
            state.set_override_backend(backend_val)
            handled = True
            messages.append(f"backend set to {backend_val}")
        persistent_change = False
        if isinstance(args.get("default-backend"), str):
            backend_val = args["default-backend"].strip().lower()

            if backend_val not in {"openrouter", "gemini"}:
                return CommandResult(
                    self.name,
                    False,
                    f"backend {backend_val} not supported",
                )

            if backend_val not in self.functional_backends:
                return CommandResult(
                    self.name,
                    False,
                    f"backend {backend_val} not functional",
                )

            self.app.state.backend_type = backend_val
            if backend_val == "gemini":
                self.app.state.backend = self.app.state.gemini_backend
            else:
                self.app.state.backend = self.app.state.openrouter_backend
            handled = True
            messages.append(f"default backend set to {backend_val}")
            persistent_change = True
        # Only allow model set if backend set did not fail
        if not backend_set_failed and isinstance(args.get("model"), str):
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
                backend_obj = getattr(self.app.state, f"{backend_part}_backend", None)
            except Exception:
                backend_obj = None

            available = backend_obj.get_available_models() if backend_obj else []

            if model_name in available:
                state.set_override_model(backend_part, model_name)
                handled = True
                messages.append(f"model set to {backend_part}:{model_name}")
            elif (
                state.interactive_mode
            ):  # If model not available AND in interactive mode
                return CommandResult(
                    self.name,
                    False,
                    f"model {backend_part}:{model_name} not available",
                )
            else:  # If model not available AND NOT in interactive mode
                state.set_override_model(backend_part, model_name, invalid=True)
                handled = True
        project_val = args.get("project") or args.get("project-name")
        if isinstance(project_val, str):
            state.set_project(project_val)
            handled = True
            messages.append(f"project set to {project_val}")
        for key in ("interactive", "interactive-mode"):
            if isinstance(args.get(key), str):
                val = self._parse_bool(args[key])
                if val is not None:
                    state.set_interactive_mode(val)
                    handled = True
                    messages.append(f"interactive mode set to {val}")
                    persistent_change = True
        if isinstance(args.get("redact-api-keys-in-prompts"), str):
            val = self._parse_bool(args["redact-api-keys-in-prompts"])
            if val is not None:
                self.app.state.api_key_redaction_enabled = val
                handled = True
                messages.append(f"redact-api-keys-in-prompts set to {val}")
                persistent_change = True
        if not handled:
            return CommandResult(self.name, False, "set: no valid parameters")
        if persistent_change and getattr(self.app.state, "config_manager", None):
            self.app.state.config_manager.save()
        return CommandResult(self.name, True, "; ".join(messages))


class UnsetCommand(BaseCommand):
    name = "unset"

    def __init__(self, app: FastAPI | None = None) -> None:
        self.app = app

    def execute(self, args: Dict[str, Any], state: "ProxyState") -> CommandResult:
        messages: List[str] = []
        persistent_change = False
        keys_to_unset = [k for k, v in args.items() if v is True]
        if "model" in keys_to_unset:
            state.unset_override_model()
            messages.append("model unset")
        if "backend" in keys_to_unset:
            state.unset_override_backend()
            messages.append("backend unset")
        if "default-backend" in keys_to_unset and self.app:
            default_type = getattr(self.app.state, "initial_backend_type", None)
            if default_type:
                self.app.state.backend_type = default_type
                if default_type == "gemini":
                    self.app.state.backend = self.app.state.gemini_backend
                else:
                    self.app.state.backend = self.app.state.openrouter_backend
            messages.append("default-backend unset")
            persistent_change = True
        if any(k in keys_to_unset for k in ("project", "project-name")):
            state.unset_project()
            messages.append("project unset")
        if any(k in keys_to_unset for k in ("interactive", "interactive-mode")):
            state.unset_interactive_mode()
            messages.append("interactive mode unset")
            persistent_change = True
        if "redact-api-keys-in-prompts" in keys_to_unset and self.app:
            self.app.state.api_key_redaction_enabled = (
                self.app.state.default_api_key_redaction_enabled
            )
            messages.append("redact-api-keys-in-prompts unset")
            persistent_change = True
        if not keys_to_unset or not messages:
            return CommandResult(self.name, False, "unset: nothing to do")
        if persistent_change and getattr(self.app.state, "config_manager", None):
            self.app.state.config_manager.save()
        return CommandResult(self.name, True, "; ".join(messages))


class HelloCommand(BaseCommand):
    name = "hello"

    def execute(self, args: Dict[str, Any], state: "ProxyState") -> CommandResult:
        state.hello_requested = True
        return CommandResult(self.name, True, "hello acknowledged")


class _FailoverBase(BaseCommand):
    def __init__(self, app: FastAPI) -> None:
        self.app = app

    def _ensure_interactive(self, state: "ProxyState", messages: List[str]) -> None:
        if not state.interactive_mode:
            state.set_interactive_mode(True)
            messages.append(
                "This llm-interactive-proxy session is now set to interactive mode"
            )


class CreateFailoverRouteCommand(_FailoverBase):
    name = "create-failover-route"

    def __init__(self, app: FastAPI) -> None:
        super().__init__(app)

    def execute(self, args: Dict[str, Any], state: "ProxyState") -> CommandResult:
        msgs: List[str] = []
        self._ensure_interactive(state, msgs)
        name = args.get("name")
        policy = str(args.get("policy", "")).lower()
        if not name or policy not in {"k", "m", "km", "mk"}:
            return CommandResult(
                self.name, False, "create-failover-route requires name and valid policy"
            )
        state.create_failover_route(name, policy)
        msgs.append(f"failover route {name} created with policy {policy}")
        if getattr(self.app.state, "config_manager", None):
            self.app.state.config_manager.save()
        return CommandResult(self.name, True, "; ".join(msgs))


class RouteAppendCommand(_FailoverBase):
    name = "route-append"

    def __init__(self, app: FastAPI) -> None:
        super().__init__(app)

    def execute(self, args: Dict[str, Any], state: "ProxyState") -> CommandResult:
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
        if getattr(self.app.state, "config_manager", None):
            self.app.state.config_manager.save()
        return CommandResult(self.name, True, "; ".join(msgs))


class RoutePrependCommand(_FailoverBase):
    name = "route-prepend"

    def __init__(self, app: FastAPI) -> None:
        super().__init__(app)

    def execute(self, args: Dict[str, Any], state: "ProxyState") -> CommandResult:
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
        if getattr(self.app.state, "config_manager", None):
            self.app.state.config_manager.save()
        return CommandResult(self.name, True, "; ".join(msgs))


class DeleteFailoverRouteCommand(_FailoverBase):
    name = "delete-failover-route"

    def __init__(self, app: FastAPI) -> None:
        super().__init__(app)

    def execute(self, args: Dict[str, Any], state: "ProxyState") -> CommandResult:
        msgs: List[str] = []
        self._ensure_interactive(state, msgs)
        name = args.get("name")
        if not name or name not in state.failover_routes:
            return CommandResult(self.name, False, f"route {name} not found")
        state.delete_failover_route(name)
        msgs.append(f"failover route {name} deleted")
        if getattr(self.app.state, "config_manager", None):
            self.app.state.config_manager.save()
        return CommandResult(self.name, True, "; ".join(msgs))


class RouteClearCommand(_FailoverBase):
    name = "route-clear"

    def __init__(self, app: FastAPI) -> None:
        super().__init__(app)

    def execute(self, args: Dict[str, Any], state: "ProxyState") -> CommandResult:
        msgs: List[str] = []
        self._ensure_interactive(state, msgs)
        name = args.get("name")
        if not name or name not in state.failover_routes:
            return CommandResult(self.name, False, f"route {name} not found")
        state.clear_route(name)
        msgs.append(f"route {name} cleared")
        if getattr(self.app.state, "config_manager", None):
            self.app.state.config_manager.save()
        return CommandResult(self.name, True, "; ".join(msgs))


class ListFailoverRoutesCommand(_FailoverBase):
    name = "list-failover-routes"

    def __init__(self, app: FastAPI) -> None:
        super().__init__(app)

    def execute(self, args: Dict[str, Any], state: "ProxyState") -> CommandResult:
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

    def __init__(self, app: FastAPI) -> None:
        super().__init__(app)

    def execute(self, args: Dict[str, Any], state: ProxyState) -> CommandResult:
        msgs: List[str] = []
        self._ensure_interactive(state, msgs)
        name = args.get("name")
        if not name or name not in state.failover_routes:
            return CommandResult(self.name, False, f"route {name} not found")
        elems = state.list_route(name)
        msgs.append(", ".join(elems) if elems else "<empty>")
        return CommandResult(self.name, True, "; ".join(msgs))
