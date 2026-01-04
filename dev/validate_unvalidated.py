#!/usr/bin/env python
"""Test all unvalidated configs against their schemas."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config.yaml_validation import validate_yaml_against_schema

pairs = [
    ("config/schemas/app_config.schema.yaml", "config/config.example.yaml"),
    ("config/schemas/app_config.schema.yaml", "config/codebuff.example.yaml"),
    ("config/schemas/app_config.schema.yaml", "config/qwen_backend.example.yaml"),
    ("config/schemas/app_config.schema.yaml", "config/identity_kilocode.example.yaml"),
    (
        "config/schemas/app_config.schema.yaml",
        "config/identity_factory_droid.example.yaml",
    ),
    ("config/schemas/app_config.schema.yaml", "config/sso_auth.example.yaml"),
    (
        "config/schemas/openai_codex_backend.schema.yaml",
        "config/backends/openai_codex.yaml.example",
    ),
    (
        "config/schemas/tool_call_reactor_config.schema.yaml",
        "config/tool_call_reactor_config.yaml",
    ),
    (
        "config/schemas/edit_precision_patterns.schema.yaml",
        "config/edit_precision_patterns.yaml",
    ),
    (
        "config/schemas/zai_default_models.schema.yaml",
        "config/backends/zai/default_models.yaml",
    ),
    (
        "config/schemas/edit_precision_temperatures.schema.yaml",
        "config/edit_precision_model_temperatures.yaml",
    ),
    ("config/schemas/health_check.yaml", "config/backends/openai_codex/backend.yaml"),
]

passed = 0
failed = 0

for schema_path, config_path in pairs:
    schema_file = Path(schema_path)
    config_file = Path(config_path)

    if not config_file.exists():
        continue

    try:
        validate_yaml_against_schema(config_file, schema_file)
        passed += 1
    except Exception as e:
        print(f"[FAIL] {config_path}: {str(e)[:200]}")
        failed += 1

print(f"\nSummary: {passed} passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)
