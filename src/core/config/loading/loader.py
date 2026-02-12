from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.core.config.dict_utils import merge_dicts
from src.core.config.merge.merger import ConfigMerger
from src.core.config.models.app_config_model import AppConfigModel
from src.core.config.parameter_resolution import ParameterResolution
from src.core.config.sources.backend_instances import (
    DEFAULT_BACKEND_INSTANCES_DIR,
    BackendInstanceEnvSource,
    BackendInstanceFileSource,
)
from src.core.config.sources.defaults import DefaultsConfigSource
from src.core.config.sources.environment import EnvironmentConfigSource
from src.core.config.sources.yaml_file import YamlFileConfigSource, _default_schema_path


class AppConfigLoader:
    """Orchestrate defaults + YAML + ENV + backend instance discovery."""

    def __init__(
        self,
        *,
        schema_path: Path | None = None,
        backend_instances_dir: Path | None = None,
    ) -> None:
        self._defaults = DefaultsConfigSource()
        self._merger = ConfigMerger()
        self._schema_path = schema_path or _default_schema_path()
        self._yaml = YamlFileConfigSource(schema_path=self._schema_path)
        self._env = EnvironmentConfigSource()
        self._instance_env = BackendInstanceEnvSource()
        self._instance_files = BackendInstanceFileSource(
            instances_dir=backend_instances_dir or DEFAULT_BACKEND_INSTANCES_DIR
        )

    def load(
        self,
        config_path: str | Path | None = None,
        *,
        environ: Mapping[str, str],
        resolution: ParameterResolution,
    ) -> AppConfigModel:
        path = Path(config_path) if config_path else None

        defaults = self._defaults.load()
        file_layer = self._yaml.load(path, resolution=resolution)

        merged_before_env: dict[str, Any] = {}
        merge_dicts(merged_before_env, defaults)
        merge_dicts(merged_before_env, file_layer)

        env_layer = self._env.load(environ, resolution=resolution)

        existing_instance_names = _collect_backend_instance_names(merged_before_env)
        instance_env_layer = self._instance_env.load(
            environ,
            existing_instance_names=existing_instance_names,
            resolution=resolution,
        )

        existing_after_env = _collect_backend_instance_names(
            self._merger.merge([merged_before_env, env_layer, instance_env_layer])
        )
        instance_file_layer = self._instance_files.load(
            existing_instance_names=existing_after_env,
            resolution=resolution,
        )

        merged = self._merger.merge(
            [defaults, file_layer, env_layer, instance_env_layer, instance_file_layer]
        )
        return AppConfigModel.model_validate(merged)


def _collect_backend_instance_names(config_dict: dict[str, Any]) -> set[str]:
    backends = config_dict.get("backends")
    if not isinstance(backends, dict):
        return set()
    names: set[str] = set()
    for key in backends:
        if isinstance(key, str) and key and key != "default_backend":
            names.add(key)
    return names
