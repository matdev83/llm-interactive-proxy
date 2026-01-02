from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    yaml = None  # type: ignore

from src.core.common.exceptions import ConfigurationError
from src.core.config.dict_utils import flatten_dict
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource
from src.core.config.semantic_validation import validate_config_semantics
from src.core.config.yaml_validation import validate_yaml_against_schema

logger = logging.getLogger(__name__)


class YamlFileConfigSource:
    """Load configuration from a YAML file with schema + semantic validation."""

    def __init__(self, *, schema_path: Path) -> None:
        self._schema_path = schema_path

    def load(
        self,
        config_path: Path | None,
        *,
        resolution: ParameterResolution,
    ) -> dict[str, Any]:
        if config_path is None:
            return {}

        if not config_path.exists():
            logger.warning("Configuration file not found: %s", config_path)
            return {}

        if config_path.suffix.lower() not in [".yaml", ".yml"]:
            raise ConfigurationError(
                message="Unsupported configuration file format",
                details={
                    "path": str(config_path),
                    "suffix": config_path.suffix,
                    "hint": "Use YAML (.yaml/.yml).",
                },
            )

        if yaml is None:
            raise ConfigurationError(
                message="PyYAML is not installed",
                details={"path": str(config_path)},
            )

        try:
            validate_yaml_against_schema(config_path, self._schema_path)

            with config_path.open(encoding="utf-8") as f:
                file_config = yaml.safe_load(f) or {}

            if not isinstance(file_config, dict):
                raise ConfigurationError(
                    message="Invalid YAML configuration format",
                    details={
                        "path": str(config_path),
                        "hint": "Top-level must be a mapping",
                    },
                )

            validate_config_semantics(file_config, config_path)

            origin = str(config_path)
            for name, value in flatten_dict(file_config).items():
                resolution.record(
                    name,
                    value,
                    ParameterSource.CONFIG_FILE,
                    origin=origin,
                )
            return file_config
        except ConfigurationError:
            raise
        except (KeyboardInterrupt, SystemExit, GeneratorExit):
            # Re-raise system-level exceptions that should never be silently caught
            raise
        except (OSError, yaml.YAMLError, TypeError, ValueError) as exc:
            # Handle expected errors: file I/O, YAML parsing, validation
            raise ConfigurationError(
                message="Error loading configuration file",
                details={"path": str(config_path)},
            ) from exc


def _default_schema_path() -> Path:
    # Prefer repo-relative resolution over cwd-dependent behavior.
    return (
        Path(__file__).resolve().parents[4]
        / "config"
        / "schemas"
        / "app_config.schema.yaml"
    )
