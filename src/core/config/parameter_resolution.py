"""Utilities for tracking configuration parameter origins and logging them."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from src.core.common.logging_utils import redact
from src.core.config.dict_utils import flatten_dict


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

    _history: dict[str, _ParameterRecord]
    # Maximum number of parameter records to prevent unbounded memory growth
    # 10,000 parameters is far more than any reasonable config would have
    _MAX_HISTORY_SIZE = 10000

    def __init__(self) -> None:
        self._history = {}

    def is_set(self, name: str) -> bool:
        """Check if a parameter has been set through any source."""
        return name in self._history

    def record(
        self,
        name: str,
        value: Any,
        source: ParameterSource,
        *,
        origin: str | None = None,
    ) -> None:
        """Record that a parameter was set by a specific source.

        Replaces any previous record for the same parameter name to prevent
        unbounded memory growth. Only the latest record is kept since that's
        what build_report() and latest_by_source() use.

        Enforces maximum history size to prevent memory leaks when many unique
        parameter names are encountered (e.g., from dynamic config loading).
        """

        # Enforce maximum size limit to prevent unbounded memory growth
        # If we're at the limit and this is a new parameter (not replacing existing),
        # evict oldest entries
        if len(self._history) >= self._MAX_HISTORY_SIZE and name not in self._history:
            # Remove oldest entries (dict maintains insertion order in Python 3.7+)
            excess = len(self._history) - self._MAX_HISTORY_SIZE + 1
            oldest_keys = list(self._history.keys())[:excess]
            for key in oldest_keys:
                del self._history[key]
            _logger = logging.getLogger(__name__)
            if _logger.isEnabledFor(logging.DEBUG):
                _logger.debug(
                    "Evicted %d oldest parameter records to enforce size limit (%d)",
                    excess,
                    self._MAX_HISTORY_SIZE,
                )

        self._history[name] = _ParameterRecord(
            value=value, source=source, origin=origin
        )

    def build_report(self, config: Any) -> list[ResolvedParameter]:
        """Build a report of all resolved parameters for the supplied config."""

        flattened = _flatten_config(config)
        report: list[ResolvedParameter] = []
        seen: set[str] = set()

        for name, value in flattened.items():
            record = self._history.get(name)
            if record:
                report.append(
                    ResolvedParameter(
                        name=name,
                        value=value,
                        source=record.source,
                        origin=record.origin,
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
        for name, record in self._history.items():
            if name in seen:
                continue
            report.append(
                ResolvedParameter(
                    name=name,
                    value=record.value,
                    source=record.source,
                    origin=record.origin,
                )
            )

        return sorted(report, key=lambda r: r.name)

    def latest_by_source(self, source: ParameterSource) -> dict[str, _ParameterRecord]:
        """Return the latest recorded values for a given source."""

        result: dict[str, _ParameterRecord] = {}
        for name, record in self._history.items():
            if record.source is source:
                result[name] = record
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

    if not isinstance(data, dict):
        raise TypeError("Unsupported configuration object type")
    return flatten_dict(data)


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
    _logger = logging.getLogger(__name__)
    try:
        if isinstance(value, dict | list):
            return json.dumps(value, sort_keys=True)
    except TypeError as _e:
        # Type error during JSON serialization - fall back to repr
        # Log for debugging purposes to help identify non-serializable values
        if _logger.isEnabledFor(logging.DEBUG):
            _logger.debug(
                "Failed to JSON-serialize value for representation; falling back to repr",
                exc_info=True,
                extra={"value_type": type(value).__name__},
            )
    return repr(value)


__all__ = [
    "ParameterResolution",
    "ParameterSource",
    "ResolvedParameter",
]
