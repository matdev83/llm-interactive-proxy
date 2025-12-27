#!/usr/bin/env python
"""Check for drift between config models and schemas."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import dataclasses

import yaml
from src.core.config.models.auth import AuthConfig
from src.core.config.models.misc import UsageTrackingConfig
from src.core.config.models.rewriting import EditPrecisionConfig
from src.core.config.models.routing import RoutingConfig
from src.core.database.config import DatabaseConfig
from src.core.domain.configuration.assessment_config import AssessmentConfig
from src.core.domain.configuration.compaction_config import CompactionConfig
from src.core.domain.configuration.health_check_config import (
    HealthCheckConfig,
    HttpCheckConfig,
    PingCheckConfig,
)
from src.core.memory.config import MemoryConfiguration


def check_model_vs_schema(model_class, schema_path, schema_section):
    """Compare model fields with schema fields."""
    schema_file = Path(schema_path)
    with schema_file.open() as f:
        schema = yaml.safe_load(f)

    schema_props = (
        schema.get("properties", {}).get(schema_section, {}).get("properties", {})
    )
    if not schema_props:
        schema_props = schema.get("properties", {}).get(schema_section, {})

    # Handle both Pydantic models (model_fields) and dataclasses (__dataclass_fields__)
    if hasattr(model_class, "model_fields"):
        # Pydantic v2 model
        model_fields = set(model_class.model_fields.keys())
    elif dataclasses.is_dataclass(model_class):
        # dataclass - exclude private fields (starting with _)
        model_fields = {
            f.name
            for f in dataclasses.fields(model_class)
            if not f.name.startswith("_")
        }
    else:
        model_fields = set()

    schema_fields = (
        set(schema_props.keys()) if isinstance(schema_props, dict) else set()
    )

    missing_in_schema = model_fields - schema_fields
    extra_in_schema = schema_fields - model_fields

    print(f"\n{model_class.__name__} ({schema_section}):")
    if missing_in_schema:
        print(f"  MISSING in schema: {sorted(missing_in_schema)}")
    if extra_in_schema:
        print(f"  EXTRA in schema: {sorted(extra_in_schema)}")
    if not missing_in_schema and not extra_in_schema:
        print("  [OK] Fields match")

    return len(missing_in_schema) == 0 and len(extra_in_schema) == 0


def main():
    checks = [
        (
            UsageTrackingConfig,
            "config/schemas/app_config.schema.yaml",
            "usage_tracking",
        ),
        (RoutingConfig, "config/schemas/app_config.schema.yaml", "routing"),
        (AuthConfig, "config/schemas/app_config.schema.yaml", "auth"),
        (
            EditPrecisionConfig,
            "config/schemas/app_config.schema.yaml",
            "edit_precision",
        ),
        (HealthCheckConfig, "config/schemas/app_config.schema.yaml", "health_check"),
        (CompactionConfig, "config/schemas/app_config.schema.yaml", "compaction"),
        (AssessmentConfig, "config/schemas/app_config.schema.yaml", "assessment"),
        (MemoryConfiguration, "config/schemas/app_config.schema.yaml", "memory"),
        (DatabaseConfig, "config/schemas/app_config.schema.yaml", "database"),
    ]

    all_ok = True
    for model, schema_path, section in checks:
        if not check_model_vs_schema(model, schema_path, section):
            all_ok = False

    # Check health check sub-configs
    with Path("config/schemas/health_check.yaml").open() as f:
        health_schema = yaml.safe_load(f)

    ping_props = (
        health_schema.get("properties", {}).get("ping", {}).get("properties", {})
    )
    http_props = (
        health_schema.get("properties", {}).get("http", {}).get("properties", {})
    )

    ping_fields = set(PingCheckConfig.model_fields.keys())
    http_fields = set(HttpCheckConfig.model_fields.keys())

    print("\nPingCheckConfig:")
    missing = ping_fields - set(ping_props.keys())
    extra = set(ping_props.keys()) - ping_fields
    if missing:
        print(f"  MISSING: {sorted(missing)}")
    if extra:
        print(f"  EXTRA: {sorted(extra)}")
    if not missing and not extra:
        print("  [OK] Fields match")

    print("\nHttpCheckConfig:")
    missing = http_fields - set(http_props.keys())
    extra = set(http_props.keys()) - http_fields
    if missing:
        print(f"  MISSING: {sorted(missing)}")
    if extra:
        print(f"  EXTRA: {sorted(extra)}")
    if not missing and not extra:
        print("  [OK] Fields match")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
