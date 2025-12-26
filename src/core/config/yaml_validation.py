from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from src.core.common.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


def _load_yaml_file(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:  # pragma: no cover
        mark = getattr(e, "problem_mark", None)
        location = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        msg = f"YAML syntax error in {path}{location}: {getattr(e, 'problem', str(e))}"
        raise ConfigurationError(
            message="Invalid YAML syntax", details={"path": str(path), "hint": msg}
        ) from e
    except FileNotFoundError as e:
        raise ConfigurationError(
            message="YAML file not found", details={"path": str(path)}
        ) from e


def _load_yaml_schema(schema_path: Path) -> dict[str, Any]:
    schema_data = _load_yaml_file(schema_path)
    if not isinstance(schema_data, dict):
        raise ConfigurationError(
            message="Invalid YAML schema format",
            details={"path": str(schema_path), "hint": "Top-level must be a mapping"},
        )
    return schema_data


def validate_yaml_against_schema(yaml_path: Path, schema_path: Path) -> None:
    """Validate a YAML file against a YAML-expressed JSON Schema.

    Raises a ValueError with a concise, actionable message on failure.
    """
    instance = _load_yaml_file(yaml_path)
    schema = _load_yaml_schema(schema_path)

    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: str(e.path))
    if not errors:
        return

    def _format_error(err: ValidationError) -> str:
        path_str = "/".join([str(p) for p in err.path]) if err.path else "<root>"
        return f"{yaml_path}: {err.message} (at {path_str})"

    messages = [_format_error(e) for e in errors]
    raise ConfigurationError(
        message="YAML schema validation failed",
        details={"path": str(yaml_path), "errors": messages},
    )


def validate_static_yaml_configs(project_root: Path) -> None:
    """Validate known YAML config files in the repo.

    This checks optional, user-editable YAML files. If a file exists and is
    invalid, raises ValueError to stop startup.
    """
    pairs: list[tuple[Path, Path]] = []

    # Edit-precision patterns
    patterns = project_root / "config" / "edit_precision_patterns.yaml"
    patterns_schema = (
        project_root / "config" / "schemas" / "edit_precision_patterns.schema.yaml"
    )
    if patterns.exists():
        pairs.append((patterns, patterns_schema))

    # Edit-precision model temperatures
    temperatures = project_root / "config" / "edit_precision_model_temperatures.yaml"
    temperatures_schema = (
        project_root / "config" / "schemas" / "edit_precision_temperatures.schema.yaml"
    )
    if temperatures.exists():
        pairs.append((temperatures, temperatures_schema))

    # ZAI default models
    zai_models = project_root / "config" / "backends" / "zai" / "default_models.yaml"
    zai_schema = project_root / "config" / "schemas" / "zai_default_models.schema.yaml"
    if zai_models.exists():
        pairs.append((zai_models, zai_schema))

    for yaml_path, schema_path in pairs:
        validate_yaml_against_schema(yaml_path, schema_path)
        logger.info("Validated YAML config: %s", yaml_path)
