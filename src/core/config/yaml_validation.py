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
    errors = sorted(validator.iter_errors(instance), key=lambda e: e.path)
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

    # Tool call reactor rules (optional file). This file in repo uses
    # a nested structure under `session.tool_call_reactor`. Validate the nested
    # object if present; otherwise, if the file is a flat object, validate as-is.
    reactor = project_root / "config" / "tool_call_reactor_config.yaml"
    reactor_schema = (
        project_root / "config" / "schemas" / "tool_call_reactor_config.schema.yaml"
    )
    if reactor.exists():
        data = _load_yaml_file(reactor)
        if (
            isinstance(data, dict)
            and isinstance(data.get("session"), dict)
            and isinstance(data["session"].get("tool_call_reactor"), dict)
        ):
            tmp = data["session"]["tool_call_reactor"]
            validator = Draft7Validator(_load_yaml_schema(reactor_schema))
            errs = sorted(validator.iter_errors(tmp), key=lambda e: e.path)
            if errs:

                def _fmt(e: ValidationError) -> str:
                    p = "/".join([str(x) for x in e.path]) if e.path else "<root>"
                    return (
                        f"{reactor} (session.tool_call_reactor): {e.message} (at {p})"
                    )

                messages = [_fmt(e) for e in errs]
                raise ConfigurationError(
                    message="YAML schema validation failed",
                    details={"path": str(reactor), "errors": messages},
                )
            logger.info(
                "Validated YAML config: %s (session.tool_call_reactor)", reactor
            )
        else:
            pairs.append((reactor, reactor_schema))

    # ZAI default models
    zai_models = project_root / "config" / "backends" / "zai" / "default_models.yaml"
    zai_schema = project_root / "config" / "schemas" / "zai_default_models.schema.yaml"
    if zai_models.exists():
        pairs.append((zai_models, zai_schema))

    for yaml_path, schema_path in pairs:
        validate_yaml_against_schema(yaml_path, schema_path)
        logger.info("Validated YAML config: %s", yaml_path)
