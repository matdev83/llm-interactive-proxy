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

    def apply(self, data: Dict[str, Any]) -> None:
        warnings: list[str] = []
        backend = data.get("default_backend")
        if isinstance(backend, str):
            if backend in self.app.state.functional_backends:
                self.app.state.backend_type = backend
                self.app.state.backend = (
                    self.app.state.gemini_backend
                    if backend == "gemini"
                    else self.app.state.openrouter_backend
                )
            else:
                # warnings.append(f"default backend {backend} not functional") # Keep or remove warning? For now, raise error.
                raise ValueError(f"default backend {backend} is not functional")

        if isinstance(data.get("interactive_mode"), bool):
            self.app.state.session_manager.default_interactive_mode = data[
                "interactive_mode"
            ]

        if isinstance(data.get("redact_api_keys_in_prompts"), bool):
            val = data["redact_api_keys_in_prompts"]
            self.app.state.api_key_redaction_enabled = val
            self.app.state.default_api_key_redaction_enabled = val

        froutes = data.get("failover_routes")
        if isinstance(froutes, dict):
            for name, route in froutes.items():
                if not isinstance(route, dict):
                    continue
                policy = route.get("policy", "k")
                elems = route.get("elements", [])
                valid_elems: list[str] = []
                if isinstance(elems, list):
                    for elem in elems:
                        if not isinstance(elem, str) or ":" not in elem:
                            continue
                        b, model = elem.split(":", 1)
                        if b not in self.app.state.functional_backends:
                            warnings.append(
                                f"route {name} element {elem} backend not functional"
                            )
                            continue
                        backend_obj = getattr(self.app.state, f"{b}_backend", None)
                        if backend_obj and model in backend_obj.get_available_models():
                            valid_elems.append(elem)
                        else:
                            warnings.append(
                                f"route {name} element {elem} model not available"
                            )
                self.app.state.failover_routes[name] = {
                    "policy": policy,
                    "elements": valid_elems,
                }
        for w in warnings:
            logger.warning(w)

        prefix = data.get("command_prefix")
        if isinstance(prefix, str):
            err = validate_command_prefix(prefix)
            if err:
                logger.warning("invalid command prefix %s: %s", prefix, err)
            else:
                self.app.state.command_prefix = prefix

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
