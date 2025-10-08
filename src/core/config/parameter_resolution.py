"""Utilities for tracking configuration parameter origins and logging them."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.core.common.logging_utils import redact


class ParameterSource(Enum):
    """Enumeration of configuration sources ordered by precedence."""

    DEFAULT = "default"
    CONFIG_FILE = "config"
    ENVIRONMENT = "environment"
    CLI = "cli"
    DERIVED = "derived"


@dataclass
class _ParameterRecord:
    value: Any
    source: ParameterSource
    origin: str | None = None


@dataclass
class ResolvedParameter:
    """Represents the final resolved value for a configuration parameter."""

    name: str
    value: Any
    source: ParameterSource
    origin: str | None = None


class ParameterResolution:
    """Track configuration values and the source that supplied them."""

    _history: dict[str, list[_ParameterRecord]]

    def __init__(self) -> None:
        self._history = {}

    def record(
        self,
        name: str,
        value: Any,
        source: ParameterSource,
        *,
        origin: str | None = None,
    ) -> None:
        """Record that a parameter was set by a specific source."""

        entries = self._history.setdefault(name, [])
        entries.append(_ParameterRecord(value=value, source=source, origin=origin))

    def build_report(self, config: Any) -> list[ResolvedParameter]:
        """Build a report of all resolved parameters for the supplied config."""

        flattened = _flatten_config(config)
        report: list[ResolvedParameter] = []
        seen: set[str] = set()

        for name, value in flattened.items():
            record = self._history.get(name)
            if record:
                entry = record[-1]
                report.append(
                    ResolvedParameter(
                        name=name, value=value, source=entry.source, origin=entry.origin
                    )
                )
            else:
                report.append(
                    ResolvedParameter(
                        name=name,
                        value=value,
                        source=ParameterSource.DEFAULT,
                        origin=None,
                    )
                )
            seen.add(name)

        # Include parameters we tracked but which might not appear in the final config
        for name, records in self._history.items():
            if name in seen:
                continue
            entry = records[-1]
            report.append(
                ResolvedParameter(
                    name=name,
                    value=entry.value,
                    source=entry.source,
                    origin=entry.origin,
                )
            )

        return sorted(report, key=lambda r: r.name)

    def latest_by_source(self, source: ParameterSource) -> dict[str, _ParameterRecord]:
        """Return the latest recorded values for a given source."""

        result: dict[str, _ParameterRecord] = {}
        for name, records in self._history.items():
            if records and records[-1].source is source:
                result[name] = records[-1]
        return result

    def log(self, logger: logging.Logger, config: Any) -> None:
        """Emit log entries describing each resolved configuration value."""

        for entry in self.build_report(config):
            redacted_value = _redact_if_needed(entry.name, entry.value)
            value_repr = _value_repr(redacted_value)
            origin_suffix = f" {entry.origin}" if entry.origin else ""
            source_label = f"{entry.source.value}{origin_suffix}".strip()
            logger.info(
                "Loaded parameter %s = %s (%s)",
                entry.name,
                value_repr,
                source_label,
            )


def _flatten_config(config: Any) -> dict[str, Any]:
    """Convert a Pydantic model or mapping into a flat dict of dotted paths."""

    if hasattr(config, "model_dump"):
        data = config.model_dump()
    elif isinstance(config, dict):
        data = config
    else:
        raise TypeError("Unsupported configuration object type")

    flattened: dict[str, Any] = {}

    def _walk(value: Any, prefix: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                new_prefix = f"{prefix}.{key}" if prefix else key
                _walk(item, new_prefix)
        else:
            flattened[prefix] = value

    _walk(data, "")
    return flattened


SECRET_FIELD_SUFFIXES = {
    "api_key",
    "api_keys",
    "auth_token",
    "token",
    "secret",
    "password",
}


def _is_secret_field(name: str) -> bool:
    last_segment = name.rsplit(".", 1)[-1]
    last_segment = last_segment.split("[")[0]
    return last_segment.lower() in SECRET_FIELD_SUFFIXES


def _redact_if_needed(name: str, value: Any) -> Any:
    if not _is_secret_field(name):
        return value
    return _mask_value(value)


def _mask_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_mask_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _mask_value(item) for key, item in value.items()}
    if value is None:
        return None
    return "***"


def _value_repr(value: Any) -> str:
    try:
        if isinstance(value, dict | list):
            return json.dumps(value, sort_keys=True)
    except TypeError:
        pass
    return repr(value)


__all__ = [
    "ParameterResolution",
    "ParameterSource",
    "ResolvedParameter",
]
