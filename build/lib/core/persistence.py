import json
import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI

from src.command_prefix import validate_command_prefix

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

    def _apply_default_backend(self, backend_value: Any) -> None:
        if isinstance(backend_value, str):
            if backend_value in self.app.state.functional_backends:
                self.app.state.backend_type = backend_value
                self.app.state.backend = (
                    self.app.state.gemini_backend
                    if backend_value == "gemini"
                    else self.app.state.openrouter_backend
                )
            else:
                raise ValueError(
                    f"Default backend '{backend_value}' is not in functional_backends."
                )

    def _apply_interactive_mode(self, mode_value: Any) -> None:
        if isinstance(mode_value, bool):
            self.app.state.session_manager.default_interactive_mode = mode_value

    def _apply_redact_api_keys(self, redact_value: Any) -> None:
        if isinstance(redact_value, bool):
            self.app.state.api_key_redaction_enabled = redact_value
            self.app.state.default_api_key_redaction_enabled = redact_value

    def _apply_command_prefix(self, prefix_value: Any) -> None:
        if isinstance(prefix_value, str):
            err = validate_command_prefix(prefix_value)
            if err:
                logger.warning("Invalid command_prefix in config '%s': %s", prefix_value, err)
            else:
                self.app.state.command_prefix = prefix_value

    def _parse_and_validate_failover_element(self, elem_str: Any, route_name: str) -> Tuple[Optional[str], Optional[str]]:
        """Parses and validates a single failover element string.
        Returns (valid_element_string, warning_message_if_any).
        """
        if not isinstance(elem_str, str) or ":" not in elem_str:
            return None, f"Invalid element format '{elem_str}' in route '{route_name}', skipping."

        backend_name, model_name = elem_str.split(":", 1)
        if backend_name not in self.app.state.functional_backends:
            return None, f"Backend '{backend_name}' in route '{route_name}' element '{elem_str}' is not functional, skipping."

        backend_instance = getattr(self.app.state, f"{backend_name}_backend", None)
        if not backend_instance or model_name not in backend_instance.get_available_models():
            return None, f"Model '{model_name}' for backend '{backend_name}' in route '{route_name}' element '{elem_str}' is not available, skipping."

        return elem_str, None # Valid element, no warning

    def _apply_failover_routes(self, froutes_value: Any) -> list[str]:
        warnings: list[str] = []
        if not isinstance(froutes_value, dict):
            return warnings

        for name, route_config in froutes_value.items():
            if not isinstance(route_config, dict):
                warnings.append(f"Failover route '{name}' config is not a dictionary, skipping.")
                continue

            policy = route_config.get("policy", "k")
            elements_config = route_config.get("elements", [])
            valid_elements: list[str] = []

            if not isinstance(elements_config, list):
                warnings.append(f"Elements for failover route '{name}' is not a list, skipping elements.")
            else:
                for elem_str in elements_config:
                    valid_element, warning = self._parse_and_validate_failover_element(elem_str, name)
                    if warning:
                        warnings.append(warning)
                    if valid_element:
                        valid_elements.append(valid_element)

            self.app.state.failover_routes[name] = {
                "policy": policy,
                "elements": valid_elements,
            }
        return warnings

    def apply(self, data: Dict[str, Any]) -> None:
        all_warnings: list[str] = []

        self._apply_default_backend(data.get("default_backend"))
        self._apply_interactive_mode(data.get("interactive_mode"))
        self._apply_redact_api_keys(data.get("redact_api_keys_in_prompts"))

        failover_warnings = self._apply_failover_routes(data.get("failover_routes"))
        all_warnings.extend(failover_warnings)

        self._apply_command_prefix(data.get("command_prefix"))

        for w in all_warnings:
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
