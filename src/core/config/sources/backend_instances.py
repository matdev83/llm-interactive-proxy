from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.core.config.parameter_resolution import ParameterResolution, ParameterSource
from src.core.services.backend_registry import backend_registry

logger = logging.getLogger(__name__)


def _default_backend_instances_dir() -> Path:
    return (
        Path(__file__).resolve().parents[4]
        / "config"
        / "backends"
        / "backend-instances"
    )


DEFAULT_BACKEND_INSTANCES_DIR = _default_backend_instances_dir()


class BackendInstanceEnvSource:
    """Discover backend instances from environment variables."""

    def load(
        self,
        environ: Mapping[str, str],
        *,
        existing_instance_names: set[str],
        resolution: ParameterResolution | None,
    ) -> dict[str, Any]:
        registered_backends = set(backend_registry.get_registered_backends())
        env_prefixes: dict[str, str] = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "zai": "ZAI_API_KEY",
            "minimax": "MINIMAX_API_KEY",
            "zenmux": "ZENMUX_API_KEY",
        }

        discovered: dict[str, dict[str, Any]] = {}

        for connector, prefix in env_prefixes.items():
            if connector not in registered_backends:
                continue

            for i in range(1, 100):
                env_key = f"{prefix}_{i}"
                api_key = environ.get(env_key)
                if not api_key:
                    continue
                instance_name = f"{connector}.{i}"

                if instance_name in existing_instance_names:
                    continue

                discovered[instance_name] = {"api_key": api_key, "connector": connector}
                if resolution is not None:
                    resolution.record(
                        f'backends["{instance_name}"].api_key',
                        api_key,
                        ParameterSource.ENVIRONMENT,
                        origin=env_key,
                    )

        if not discovered:
            return {}

        return {"backends": discovered}


class BackendInstanceFileSource:
    """Load backend instance configs from per-instance YAML files."""

    _filename_pattern = re.compile(r"^(?P<connector>[^.]+)\.(?P<name>.+)\.yaml$")

    def __init__(self, *, instances_dir: Path = DEFAULT_BACKEND_INSTANCES_DIR) -> None:
        self._instances_dir = instances_dir

    def load(
        self,
        *,
        existing_instance_names: set[str],
        resolution: ParameterResolution | None,
    ) -> dict[str, Any]:
        registered_backends = set(backend_registry.get_registered_backends())

        discovered: dict[str, dict[str, Any]] = {}
        file_configured_instances: set[str] = set()

        if self._instances_dir.exists():
            for config_file in self._instances_dir.glob("*.yaml"):
                match = self._filename_pattern.match(config_file.name)
                if not match:
                    continue

                connector = match.group("connector")
                if connector not in registered_backends:
                    logger.warning(
                        "Skipping config file %s: connector '%s' not registered",
                        config_file.name,
                        connector,
                    )
                    continue

                instance_name = f"{connector}.{match.group('name')}"
                file_configured_instances.add(instance_name)

                try:
                    import yaml

                    with config_file.open(encoding="utf-8") as f:
                        file_config = yaml.safe_load(f) or {}
                    if not isinstance(file_config, dict):
                        logger.warning(
                            "Skipping invalid config file %s: content is not a dict",
                            config_file.name,
                        )
                        continue

                    file_config = dict(file_config)
                    file_config["connector"] = connector
                    discovered[instance_name] = file_config

                    if resolution is not None:
                        for key, value in file_config.items():
                            resolution.record(
                                f'backends["{instance_name}"].{key}',
                                value,
                                ParameterSource.CONFIG_FILE,
                                origin=str(config_file),
                            )

                    logger.info("Loaded backend instance config: %s", instance_name)
                except Exception as exc:
                    logger.error(
                        "Error loading backend instance config %s: %s",
                        config_file.name,
                        str(exc),
                    )

        self._validate_credentials_uniqueness(discovered)
        self._ensure_file_based_defaults(
            discovered,
            existing_instance_names=existing_instance_names,
            registered_backends=registered_backends,
        )

        if not discovered:
            return {}
        return {"backends": discovered}

    def _validate_credentials_uniqueness(
        self, discovered: dict[str, dict[str, Any]]
    ) -> None:
        file_based_connectors = {
            "qwen-oauth",
            "gemini-oauth-free",
            "gemini-oauth-plan",
            "gemini-oauth-antigravity",
            "gemini-cli-cloud-project",
            "anthropic-oauth",
        }

        connector_paths: dict[str, dict[str, str]] = {}

        for instance_name, config in discovered.items():
            connector = str(config.get("connector") or instance_name.split(".")[0])
            if connector not in file_based_connectors:
                continue

            creds_path = config.get("credentials_path")
            if not creds_path:
                continue

            normalized_path = str(Path(str(creds_path)).resolve())
            connector_paths.setdefault(connector, {})
            if normalized_path in connector_paths[connector]:
                prev_instance = connector_paths[connector][normalized_path]
                msg = (
                    f"Duplicate credentials path '{creds_path}' detected for connector "
                    f"'{connector}' in instances '{prev_instance}' and '{instance_name}'"
                )
                raise ValueError(msg)

            connector_paths[connector][normalized_path] = instance_name

    def _ensure_file_based_defaults(
        self,
        discovered: dict[str, dict[str, Any]],
        *,
        existing_instance_names: set[str],
        registered_backends: set[str],
    ) -> None:
        file_based_connectors = {
            "qwen-oauth",
            "gemini-oauth-free",
            "gemini-oauth-plan",
            "gemini-oauth-antigravity",
            "gemini-cli-cloud-project",
            "anthropic-oauth",
        }

        for connector in file_based_connectors:
            if connector not in registered_backends:
                continue

            has_any_instance = any(
                name.startswith(f"{connector}.")
                for name in existing_instance_names.union(discovered.keys())
            )
            if has_any_instance:
                continue

            instance_name = f"{connector}.1"
            discovered[instance_name] = {"connector": connector}
            logger.info(
                "Created default instance '%s' for file-based connector '%s'",
                instance_name,
                connector,
            )
