from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Mapping

from src.core.config.parameter_resolution import ParameterResolution, ParameterSource

logger = logging.getLogger(__name__)


def get_openrouter_headers(cfg: dict[str, str], api_key: str) -> dict[str, str]:
    """Construct headers for OpenRouter requests."""
    referer: str = cfg.get("app_site_url", "http://localhost:8000")
    x_title: str = cfg.get("app_x_title", "InterceptorProxy")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": referer,
        "X-Title": x_title,
    }


def _collect_api_keys_from_env(
    base_name: str,
    env: Mapping[str, str],
    resolution: ParameterResolution | None = None,
) -> dict[str, str]:
    single_key = env.get(base_name)
    numbered_keys: dict[str, str] = {}
    numbered_key_names: list[str] = []
    for index in range(1, 21):
        key_name = f"{base_name}_{index}"
        key = env.get(key_name)
        if key:
            numbered_keys[key_name] = key
            numbered_key_names.append(key_name)

    if single_key and numbered_keys:
        logger.warning(
            "Both %s and %s_<n> environment variables are set. Prioritizing %s_<n> and ignoring %s.",
            base_name,
            base_name,
            base_name,
            base_name,
        )
        if resolution is not None:
            resolution.record(
                f"backends.{base_name.lower().replace('_', '')}.api_key",
                list(numbered_keys.values()),
                ParameterSource.ENVIRONMENT,
                origin=",".join(numbered_key_names),
            )
        return numbered_keys

    if single_key:
        result = {base_name: single_key}
        if resolution is not None:
            resolution.record(
                f"backends.{base_name.lower().replace('_', '')}.api_key",
                list(result.values()),
                ParameterSource.ENVIRONMENT,
                origin=base_name,
            )
        return result

    if resolution is not None and numbered_keys:
        resolution.record(
            f"backends.{base_name.lower().replace('_', '')}.api_key",
            list(numbered_keys.values()),
            ParameterSource.ENVIRONMENT,
            origin=",".join(numbered_key_names),
        )
    return numbered_keys


def _process_api_keys(keys_string: str) -> list[str]:
    keys = keys_string.split(",")
    result: list[str] = []
    for key in keys:
        stripped_key = key.strip()
        if stripped_key:
            result.append(stripped_key)
    return result


def _get_api_keys_from_env(
    env: Mapping[str, str],
    resolution: ParameterResolution | None = None,
) -> list[str]:
    result: list[str] = []
    api_keys_raw = env.get("API_KEYS")
    if api_keys_raw and isinstance(api_keys_raw, str):
        result.extend(_process_api_keys(api_keys_raw))

    if result and resolution is not None:
        resolution.record(
            "auth.api_keys",
            result,
            ParameterSource.ENVIRONMENT,
            origin="API_KEYS",
        )
    return result


def _env_to_bool(
    name: str,
    default: bool,
    env: Mapping[str, str],
    *,
    path: str | None = None,
    resolution: ParameterResolution | None = None,
) -> bool:
    value = env.get(name)
    if value is None:
        return default
    result = value.strip().lower() in {"1", "true", "yes", "on"}
    if resolution is not None and path is not None:
        resolution.record(path, result, ParameterSource.ENVIRONMENT, origin=name)
    return result


def _env_to_int(
    name: str,
    default: int,
    env: Mapping[str, str],
    *,
    path: str | None = None,
    resolution: ParameterResolution | None = None,
) -> int:
    value = env.get(name)
    if value is None:
        return default
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    if resolution is not None and path is not None and value is not None:
        resolution.record(path, result, ParameterSource.ENVIRONMENT, origin=name)
    return result


def _env_to_float(
    name: str,
    default: float,
    env: Mapping[str, str],
    *,
    path: str | None = None,
    resolution: ParameterResolution | None = None,
) -> float:
    value = env.get(name)
    if value is None:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    if resolution is not None and path is not None and value is not None:
        resolution.record(path, result, ParameterSource.ENVIRONMENT, origin=name)
    return result


def _get_env_value(
    env: Mapping[str, str],
    name: str,
    default: Any,
    *,
    path: str | None = None,
    resolution: ParameterResolution | None = None,
) -> Any:
    value = env.get(name, default)
    if resolution is not None and path is not None and value != default:
        resolution.record(path, value, ParameterSource.ENVIRONMENT, origin=name)
    return value


def _to_int(value: str, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _to_float(value: str, fallback: float | None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _merge_dicts(d1: dict[str, Any], d2: dict[str, Any]) -> dict[str, Any]:
    for key, value in d2.items():
        if key in d1 and isinstance(d1[key], dict) and isinstance(value, dict):
            _merge_dicts(d1[key], value)
        else:
            d1[key] = value
    return d1


def _set_by_path(target: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current: dict[str, Any] = target
    for key in parts[:-1]:
        current = current.setdefault(key, {})  # type: ignore[assignment]
    current[parts[-1]] = value


def _get_by_path(source: dict[str, Any], path: str) -> Any:
    parts = path.split(".")
    current: Any = source
    for key in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _flatten_dict(data: dict[str, Any]) -> dict[str, Any]:
    flattened: dict[str, Any] = {}

    def _walk(value: Any, prefix: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                new_prefix = f"{prefix}.{key}" if prefix else key
                _walk(child, new_prefix)
        else:
            flattened[prefix] = value

    _walk(data, "")
    return flattened


def load_config(
    config_path: str | Path | None = None,
    *,
    resolution: ParameterResolution | None = None,
    environ: Mapping[str, str] | None = None,
) -> "AppConfig":
    from src.core.config.app_config import AppConfig

    env = os.environ if environ is None else environ
    res = resolution or ParameterResolution()

    config_data: dict[str, Any] = AppConfig().model_dump()

    if config_path:
        try:
            import yaml

            path = Path(config_path)
            if not path.exists():
                logger.warning("Configuration file not found: %s", config_path)
            else:
                if path.suffix.lower() not in {".yaml", ".yml"}:
                    raise ValueError(
                        f"Unsupported configuration file format: {path.suffix}. Use YAML (.yaml/.yml)."
                    )

                with path.open(encoding="utf-8") as file_handle:
                    file_config: dict[str, Any] = yaml.safe_load(file_handle) or {}

                from src.core.config.semantic_validation import validate_config_semantics
                from src.core.config.yaml_validation import validate_yaml_against_schema

                schema_path = Path.cwd() / "config" / "schemas" / "app_config.schema.yaml"
                validate_yaml_against_schema(path, schema_path)
                validate_config_semantics(file_config, path)

                _merge_dicts(config_data, file_config)
                origin = str(path)
                for name, value in _flatten_dict(file_config).items():
                    res.record(
                        name,
                        value,
                        ParameterSource.CONFIG_FILE,
                        origin=origin,
                    )
        except Exception as exc:  # type: ignore[misc]
            logger.critical("Error loading configuration file: %s", exc)
            raise

    env_config = AppConfig.from_env(environ=env, resolution=res)
    env_dump = env_config.model_dump()
    for name in res.latest_by_source(ParameterSource.ENVIRONMENT):
        value = _get_by_path(env_dump, name)
        _set_by_path(config_data, name, value)

    return AppConfig.model_validate(config_data)


__all__ = [
    "get_openrouter_headers",
    "_collect_api_keys_from_env",
    "_process_api_keys",
    "_get_api_keys_from_env",
    "_env_to_bool",
    "_env_to_int",
    "_env_to_float",
    "_get_env_value",
    "_to_int",
    "_to_float",
    "_merge_dicts",
    "_set_by_path",
    "_get_by_path",
    "_flatten_dict",
    "load_config",
]
