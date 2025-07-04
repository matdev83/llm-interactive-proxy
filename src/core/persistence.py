import json
import logging
from pathlib import Path
from typing import Any, Dict

from src.command_prefix import validate_command_prefix

from fastapi import FastAPI

logger = logging.getLogger(__name__)


class ConfigManager:
    def __init__(self, app: FastAPI, path: str) -> None:
        self.app = app
        self.path = Path(path)

    def load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text())
        except Exception as e:  # pragma: no cover - should rarely happen
            logger.warning("Failed to load config file %s: %s", self.path, e)
            return
        self.apply(data)

    def _apply_default_backend(self, backend: Any, warnings: list[str]) -> None:
        if isinstance(backend, str):
            if backend in self.app.state.functional_backends:
                self.app.state.backend_type = backend
                self.app.state.backend = (
                    self.app.state.gemini_backend
                    if backend == "gemini"
                    else self.app.state.openrouter_backend
                )
            else:
                warnings.append(f"Configured default backend '{backend}' is not functional.")

    def _apply_interactive_mode(self, mode: Any) -> None:
        if isinstance(mode, bool):
            self.app.state.session_manager.default_interactive_mode = mode

    def _apply_redact_api_keys(self, redact: Any) -> None:
        if isinstance(redact, bool):
            self.app.state.api_key_redaction_enabled = redact
            self.app.state.default_api_key_redaction_enabled = redact # Persisted value becomes the new default

    def _apply_single_failover_route_element(self, elem_str: str, route_name: str, warnings: list[str]) -> str | None:
        if not isinstance(elem_str, str) or ":" not in elem_str:
            warnings.append(f"Route '{route_name}' element '{elem_str}' is invalid format (expected backend:model).")
            return None

        backend_name, model_name = elem_str.split(":", 1)
        if backend_name not in self.app.state.functional_backends:
            warnings.append(f"Route '{route_name}' element '{elem_str}' backend '{backend_name}' is not functional.")
            return None

        backend_obj = getattr(self.app.state, f"{backend_name}_backend", None)
        if not backend_obj or model_name not in backend_obj.get_available_models(): # pragma: no cover
            warnings.append(f"Route '{route_name}' element '{elem_str}' model '{model_name}' is not available for backend '{backend_name}'.")
            return None
        return elem_str


    def _apply_failover_routes(self, froutes: Any, warnings: list[str]) -> None:
        if not isinstance(froutes, dict):
            return

        for name, route_data in froutes.items():
            if not isinstance(route_data, dict):
                warnings.append(f"Failover route '{name}' data is not a dictionary, skipping.")
                continue

            policy = route_data.get("policy", "k") # Default to 'k' (known good) or some other sensible default
            elements_data = route_data.get("elements", [])

            valid_elements: list[str] = []
            if isinstance(elements_data, list):
                for elem_str in elements_data:
                    valid_elem = self._apply_single_failover_route_element(elem_str, name, warnings)
                    if valid_elem:
                        valid_elements.append(valid_elem)
            else:
                warnings.append(f"Failover route '{name}' elements is not a list, skipping elements.")

            self.app.state.failover_routes[name] = {
                "policy": policy,
                "elements": valid_elements,
            }
            if not valid_elements and elements_data: # If original elements were there but none were valid
                 warnings.append(f"Failover route '{name}' had elements defined, but none were valid or available.")


    def _apply_command_prefix(self, prefix: Any, warnings: list[str]) -> None:
        if isinstance(prefix, str):
            err = validate_command_prefix(prefix)
            if err:
                warnings.append(f"Invalid command prefix '{prefix}' from config: {err}")
            else:
                self.app.state.command_prefix = prefix

    def apply(self, data: Dict[str, Any]) -> None:
        warnings: list[str] = []

        self._apply_default_backend(data.get("default_backend"), warnings)
        self._apply_interactive_mode(data.get("interactive_mode"))
        self._apply_redact_api_keys(data.get("redact_api_keys_in_prompts"))
        self._apply_failover_routes(data.get("failover_routes"), warnings)
        self._apply_command_prefix(data.get("command_prefix"), warnings)

        for w in warnings:
            logger.warning(w)

    def collect(self) -> Dict[str, Any]:
        return {
            "default_backend": self.app.state.backend_type,
            "interactive_mode": self.app.state.session_manager.default_interactive_mode,
            "failover_routes": self.app.state.failover_routes,
            "redact_api_keys_in_prompts": self.app.state.api_key_redaction_enabled,
            "command_prefix": self.app.state.command_prefix,
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = self.collect()
        with self.path.open("w") as f:
            json.dump(data, f, indent=2)
