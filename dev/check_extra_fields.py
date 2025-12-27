"""Check for extra fields in schemas that aren't in config models."""

import dataclasses
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

# Import config models
from src.core.config.models.app_config_model import AppConfigModel
from src.core.config.models.logging import LoggingConfig
from src.core.config.models.misc import (
    CodebuffConfig,
    EmptyResponseConfig,
    UsageTrackingConfig,
)
from src.core.config.models.rewriting import EditPrecisionConfig, RewritingConfig
from src.core.config.models.session import SessionConfig, ToolCallReactorConfig
from src.core.domain.configuration.assessment_config import AssessmentConfig
from src.core.domain.configuration.compaction_config import CompactionConfig
from src.core.domain.configuration.replacement_config import ReplacementConfig


def get_pydantic_fields(cls) -> set[str]:
    """Get fields from Pydantic model."""
    return set(cls.model_fields.keys())


def get_dataclass_fields(cls) -> set[str]:
    """Get fields from dataclass, excluding private fields (starting with _)."""
    return {f.name for f in dataclasses.fields(cls) if not f.name.startswith("_")}


def check_model_schema_match(
    model_name: str,
    model_fields: set[str],
    schema_props: dict[str, Any],
    context: str = "",
) -> bool:
    """Check if model fields match schema properties."""
    schema_fields = set(schema_props.keys())

    missing_in_schema = model_fields - schema_fields
    extra_in_schema = schema_fields - model_fields

    if missing_in_schema or extra_in_schema:
        print(f"\n[DRIFT] {model_name} ({context})")
        if missing_in_schema:
            print(f"  Missing in schema: {sorted(missing_in_schema)}")
        if extra_in_schema:
            print(f"  Extra in schema: {sorted(extra_in_schema)}")
        return True
    return False


# Load app_config schema
schema_path = Path("config/schemas/app_config.schema.yaml")
with schema_path.open() as f:
    app_schema = yaml.safe_load(f)

print("Checking for schema/model drift...\n")

issues = False

# Check top-level fields
print("=== Top-level fields ===")
top_level_props = app_schema.get("properties", {})
app_config_fields = get_pydantic_fields(AppConfigModel)
issues |= check_model_schema_match("AppConfigModel", app_config_fields, top_level_props)

# Check nested configs
nested_configs = [
    ("usage_tracking", "UsageTrackingConfig", get_pydantic_fields(UsageTrackingConfig)),
    ("assessment", "AssessmentConfig", get_dataclass_fields(AssessmentConfig)),
    ("compaction", "CompactionConfig", get_dataclass_fields(CompactionConfig)),
    ("replacement", "ReplacementConfig", get_pydantic_fields(ReplacementConfig)),
    ("edit_precision", "EditPrecisionConfig", get_pydantic_fields(EditPrecisionConfig)),
    ("rewriting", "RewritingConfig", get_pydantic_fields(RewritingConfig)),
    ("codebuff", "CodebuffConfig", get_pydantic_fields(CodebuffConfig)),
    ("empty_response", "EmptyResponseConfig", get_pydantic_fields(EmptyResponseConfig)),
    ("session", "SessionConfig", get_pydantic_fields(SessionConfig)),
    ("logging", "LoggingConfig", get_pydantic_fields(LoggingConfig)),
]

for section_name, config_name, fields in nested_configs:
    if section_name in top_level_props:
        section_schema = top_level_props[section_name].get("properties", {})
        print(f"\n=== {section_name} ===")
        issues |= check_model_schema_match(
            config_name, fields, section_schema, section_name
        )

# Check tool_call_reactor config
tool_schema_path = Path("config/schemas/tool_call_reactor_config.schema.yaml")
with tool_schema_path.open() as f:
    tool_schema = yaml.safe_load(f)

print("\n=== tool_call_reactor ===")
tool_fields = get_pydantic_fields(ToolCallReactorConfig)
issues |= check_model_schema_match(
    "ToolCallReactorConfig", tool_fields, tool_schema.get("properties", {})
)

if not issues:
    print("\n[OK] No schema/model drift detected!")
else:
    print("\n[DRIFT FOUND] Some schemas don't match config models")
    sys.exit(1)
