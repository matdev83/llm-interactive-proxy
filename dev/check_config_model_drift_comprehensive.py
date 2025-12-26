#!/usr/bin/env python
"""Comprehensive check for drift between config models and schemas."""
import sys
from pathlib import Path
from dataclasses import fields

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from src.core.config.models.misc import UsageTrackingConfig, CodebuffConfig, EmptyResponseConfig
from src.core.config.models.routing import RoutingConfig
from src.core.config.models.auth import AuthConfig, BruteForceProtectionConfig
from src.core.config.models.rewriting import RewritingConfig, EditPrecisionConfig
from src.core.config.models.backends import BackendConfig
from src.core.config.models.session import (
    ToolCallReactorConfig,
    PlanningPhaseConfig,
    SessionContinuityConfig,
    StreamingSamplerConfig,
    SessionConfig,
)
from src.core.config.models.end_of_session import EndOfSessionConfig
from src.core.domain.configuration.health_check_config import (
    HealthCheckConfig,
    PingCheckConfig,
    HttpCheckConfig,
)
from src.core.domain.configuration.compaction_config import CompactionConfig
from src.core.domain.configuration.assessment_config import AssessmentConfig
from src.core.domain.configuration.reasoning_aliases_config import (
    ReasoningAliasesConfig,
    ReasoningMode,
    ModelReasoningAliases,
)
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.memory.config import MemoryConfiguration
from src.core.database.config import DatabaseConfig

already_fixed_schemas = {
    "config/schemas/app_config.schema.yaml",
    "config/schemas/tool_call_reactor_config.schema.yaml",
    "config/schemas/edit_precision_temperatures.schema.yaml",
    "config/schemas/assessment_config.schema.yaml",
    "config/schemas/replacement_config.schema.yaml",
    "config/schemas/edit_precision_patterns.schema.yaml",
    "config/schemas/zai_default_models.schema.yaml",
    "config/schemas/openai_codex_backend.schema.yaml",
}


def check_pydantic_model(model_class, schema_path, schema_section):
    """Compare Pydantic model fields with schema fields."""
    schema_file = Path(schema_path)
    if not schema_file.exists():
        return None, None, f"schema not found: {schema_path}"
    
    if str(schema_file) in already_fixed_schemas:
        return None, None, "already fixed"
    
    with schema_file.open() as f:
        schema = yaml.safe_load(f)
    
    schema_section_obj = schema.get("properties", {}).get(schema_section, {})
    schema_props = schema_section_obj.get("properties", {})
    if not schema_props:
        schema_props = schema_section_obj
    
    model_fields = set(model_class.model_fields.keys())
    schema_fields = set(schema_props.keys()) if isinstance(schema_props, dict) else set()
    
    missing_in_schema = model_fields - schema_fields
    extra_in_schema = schema_fields - model_fields
    
    return missing_in_schema, extra_in_schema, None


def check_dataclass_model(dataclass_class, schema_path, schema_section):
    """Compare dataclass fields with schema fields."""
    schema_file = Path(schema_path)
    if not schema_file.exists():
        return None, None, f"schema not found: {schema_path}"
    
    if str(schema_file) in already_fixed_schemas:
        return None, None, "already fixed"
    
    with schema_file.open() as f:
        schema = yaml.safe_load(f)
    
    schema_section_obj = schema.get("properties", {}).get(schema_section, {})
    schema_props = schema_section_obj.get("properties", {})
    if not schema_props:
        schema_props = schema_section_obj
    
    dataclass_fields = {f.name for f in fields(dataclass_class)}
    schema_fields = set(schema_props.keys()) if isinstance(schema_props, dict) else set()
    
    # Skip internal fields
    internal_fields = {f for f in dataclass_fields if f.startswith('_')}
    dataclass_fields -= internal_fields
    
    missing_in_schema = dataclass_fields - schema_fields
    extra_in_schema = schema_fields - dataclass_fields
    
    return missing_in_schema, extra_in_schema, None


def check_json_schema_model(model_class, schema_path, root_section=None):
    """Check model against JSON schema file."""
    import json
    
    schema_file = Path(schema_path)
    if not schema_file.exists():
        return None, None, f"schema not found: {schema_path}"
    
    if str(schema_file) in already_fixed_schemas:
        return None, None, "already fixed"
    
    with schema_file.open() as f:
        schema = json.load(f)
    
    # Get the relevant section from the schema
    if root_section:
        schema_section = schema.get("properties", {}).get(root_section, {})
        schema_props = schema_section.get("properties", {})
    else:
        schema_props = schema.get("properties", {})
    
    model_fields = set(model_class.model_fields.keys())
    schema_fields = set(schema_props.keys()) if isinstance(schema_props, dict) else set()
    
    missing_in_schema = model_fields - schema_fields
    extra_in_schema = schema_fields - model_fields
    
    return missing_in_schema, extra_in_schema, None


def main():
    issues = []
    
    # Check all Pydantic models in app_config.schema.yaml
    checks = [
        (UsageTrackingConfig, "config/schemas/app_config.schema.yaml", "usage_tracking"),
        (RoutingConfig, "config/schemas/app_config.schema.yaml", "routing"),
        (AuthConfig, "config/schemas/app_config.schema.yaml", "auth"),
        (CodebuffConfig, "config/schemas/app_config.schema.yaml", "codebuff"),
        (EmptyResponseConfig, "config/schemas/app_config.schema.yaml", "empty_response"),
        (EndOfSessionConfig, "config/schemas/app_config.schema.yaml", "end_of_session"),
        (HealthCheckConfig, "config/schemas/app_config.schema.yaml", "health_check"),
        (MemoryConfiguration, "config/schemas/app_config.schema.yaml", "memory"),
        (DatabaseConfig, "config/schemas/app_config.schema.yaml", "database"),
        (ToolCallReactorConfig, "config/schemas/app_config.schema.yaml", "session.tool_call_reactor"),
        (PlanningPhaseConfig, "config/schemas/app_config.schema.yaml", "session.planning_phase"),
        (SessionContinuityConfig, "config/schemas/app_config.schema.yaml", "session.session_continuity"),
        (StreamingSamplerConfig, "config/schemas/app_config.schema.yaml", "session.streaming_sampler"),
    ]
    
    for model, schema_path, section in checks:
        missing, extra, error = check_pydantic_model(model, schema_path, section)
        if error:
            continue  # Skip already fixed or missing schemas
        if missing or extra:
            issues.append((model.__name__, schema_path, section, "pydantic", missing, extra))
    
    # Check dataclass models in app_config.schema.yaml
    dataclass_checks = [
        (CompactionConfig, "config/schemas/app_config.schema.yaml", "compaction"),
        (AssessmentConfig, "config/schemas/app_config.schema.yaml", "assessment"),
        (ReplacementConfig, "config/schemas/app_config.schema.yaml", "replacement"),
    ]
    
    for model, schema_path, section in dataclass_checks:
        missing, extra, error = check_dataclass_model(model, schema_path, section)
        if error:
            continue
        if missing or extra:
            issues.append((model.__name__, schema_path, section, "dataclass", missing, extra))
    
    # Check health_check standalone schema
    if Path("config/schemas/health_check.yaml").exists():
        with Path("config/schemas/health_check.yaml").open() as f:
            health_schema = yaml.safe_load(f)
        
        ping_props = health_schema.get("properties", {}).get("ping", {}).get("properties", {})
        http_props = health_schema.get("properties", {}).get("http", {}).get("properties", {})
        
        ping_fields = set(PingCheckConfig.model_fields.keys())
        http_fields = set(HttpCheckConfig.model_fields.keys())
        
        ping_missing = ping_fields - set(ping_props.keys())
        ping_extra = set(ping_props.keys()) - ping_fields
        http_missing = http_fields - set(http_props.keys())
        http_extra = set(http_props.keys()) - http_fields
        
        if ping_missing
