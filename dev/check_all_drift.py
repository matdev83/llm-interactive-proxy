#!/usr/bin/env python
"""Check all schema/example pairs for drift."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config.yaml_validation import validate_yaml_against_schema

# Define schema to example file mappings
schema_example_pairs = [
    (
        "config/schemas/app_config.schema.yaml",
        [
            "config/config.example.yaml",
            "config/codebuff.example.yaml",
            "config/qwen_backend.example.yaml",
            "config/identity_kilocode.example.yaml",
            "config/identity_factory_droid.example.yaml",
            "config/sso_auth.example.yaml",
        ],
    ),
    (
        "config/schemas/openai_codex_backend.schema.yaml",
        [
            "config/backends/openai_codex/backend.example.yaml",
            "config/backends/openai_codex.yaml.example",
        ],
    ),
    (
        "config/schemas/tool_call_reactor_config.schema.yaml",
        [
            # This is a real config file, not an example
        ],
    ),
    (
        "config/schemas/edit_precision_temperatures.schema.yaml",
        [
            # This is a real config file, not an example
        ],
    ),
    (
        "config/schemas/edit_precision_patterns.schema.yaml",
        [
            # This is a real config file, not an example
        ],
    ),
    (
        "config/schemas/zai_default_models.schema.yaml",
        [
            # This is a real config file, not an example
        ],
    ),
    (
        "config/schemas/replacement_config.schema.yaml",
        [
            # No example file for this one
        ],
    ),
    (
        "config/schemas/reasoning_aliases.schema.yaml",
        [
            # This is a real config file, not an example
        ],
    ),
    (
        "config/schemas/assessment_config.schema.yaml",
        [
            # No example file for this one
        ],
    ),
    (
        "config/schemas/health_check.yaml",
        [
            # No example file for this one
        ],
    ),
]

total_checks = 0
passed = 0
failed = 0

print("Comprehensive Schema Drift Check\n")
print("=" * 60)

for schema_path_str, example_paths in schema_example_pairs:
    schema_path = Path(schema_path_str)
    if not schema_path.exists():
        print(f"\n[SKIP] Schema not found: {schema_path_str}")
        continue

    for example_path_str in example_paths:
        example_path = Path(example_path_str)
        if not example_path.exists():
            print(f"\n[SKIP] Example not found: {example_path_str}")
            continue

        total_checks += 1
        try:
            validate_yaml_against_schema(example_path, schema_path)
            print(f"[OK] {example_path.name}")
            passed += 1
        except Exception as e:
            print(f"[FAIL] {example_path.name}")
            print(f"       Error: {str(e)[:150]}")
            failed += 1

print("\n" + "=" * 60)
print(f"Summary: {passed}/{total_checks} passed, {failed}/{total_checks} failed")

# Check for real config files that should validate
real_configs = [
    (
        "config/schemas/tool_call_reactor_config.schema.yaml",
        "config/tool_call_reactor_config.yaml",
    ),
    (
        "config/schemas/openai_codex_backend.schema.yaml",
        "config/backends/openai_codex/backend.yaml",
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
]

print("\n" + "=" * 60)
print("Real Config Files Check\n")

for schema_path_str, config_path_str in real_configs:
    schema_path = Path(schema_path_str)
    config_path = Path(config_path_str)
    if not config_path.exists():
        print(f"[SKIP] Config not found: {config_path_str}")
        continue

    total_checks += 1
    try:
        validate_yaml_against_schema(config_path, schema_path)
        print(f"[OK] {config_path.name}")
        passed += 1
    except Exception as e:
        print(f"[FAIL] {config_path.name}")
        print(f"       Error: {str(e)[:150]}")
        failed += 1

print("\n" + "=" * 60)
print(f"Final Summary: {passed}/{total_checks} passed, {failed}/{total_checks} failed")
