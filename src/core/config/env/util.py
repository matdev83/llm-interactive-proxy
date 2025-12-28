from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from src.core.common.exceptions import ConfigurationError
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource


def process_api_keys(keys_string: str) -> list[str]:
    keys = keys_string.split(",")
    result: list[str] = []
    for key in keys:
        stripped = key.strip()
        if stripped:
            result.append(stripped)
    return result


def parse_csv_list(value: str) -> list[str]:
    items = value.split(",")
    result: list[str] = []
    for item in items:
        stripped = item.strip()
        if stripped:
            result.append(stripped)
    return result


def get_api_keys_from_env(
    env: Mapping[str, str], resolution: ParameterResolution | None = None
) -> list[str]:
    result: list[str] = []
    api_keys_raw: str | None = env.get("API_KEYS")
    if api_keys_raw and isinstance(api_keys_raw, str):
        result.extend(process_api_keys(api_keys_raw))

    if result and resolution is not None:
        resolution.record(
            "auth.api_keys",
            result,
            ParameterSource.ENVIRONMENT,
            origin="API_KEYS",
        )
    return result


def env_to_bool(
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


def env_to_int(
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


def env_to_float(
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


def get_env_value(
    env: Mapping[str, str],
    name: str,
    default: Any,
    *,
    path: str,
    resolution: ParameterResolution | None = None,
    transform: Callable[[str], Any] | None = None,
) -> Any:
    if name in env:
        raw_value = env[name]
        try:
            value = transform(raw_value) if transform is not None else raw_value
        except Exception as exc:
            raise ConfigurationError(
                message="Invalid environment variable",
                details={"env": name, "path": path},
            ) from exc
        if resolution is not None:
            resolution.record(path, value, ParameterSource.ENVIRONMENT, origin=name)
        return value
    return default


def to_int(value: str, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def to_float(value: str, fallback: float | None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback
