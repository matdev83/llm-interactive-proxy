"""Comprehensive check for config validation issues."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config.yaml_validation import validate_yaml_against_schema

# Define all config files and their expected schemas
config_schema_pairs = [
    # Main config examples
    ("config/config.example.yaml", "config/schemas/app_config.schema.yaml"),
    ("config/codebuff.example.yaml", "config/schemas/app_config.schema.yaml"),
    ("config/qwen_backend.example.yaml", "config/schemas/app_config.schema.yaml"),
    ("config/identity_kilocode.example.yaml", "config/schemas/app_config.schema.yaml"),
    (
        "config/identity_factory_droid.example.yaml",
        "config/schemas/app_config.schema.yaml",
    ),
    ("config/sso_auth.example.yaml", "config/schemas/app_config.schema.yaml"),
    # Standalone configs
    (
        "config/tool_call_reactor_config.yaml",
        "config/schemas/tool_call_reactor_config.schema.yaml",
    ),
    (
        "config/edit_precision_model_temperatures.yaml",
        "config/schemas/edit_precision_temperatures.schema.yaml",
    ),
    (
        "config/edit_precision_patterns.yaml",
        "config/schemas/edit_precision_patterns.schema.yaml",
    ),
    (
        "config/reasoning_aliases.yaml.example",
        "config/schemas/reasoning_aliases.schema.yaml",
    ),
    # Backend configs
    (
        "config/backends/openai_codex/backend.yaml",
        "config/schemas/openai_codex_backend.schema.yaml",
    ),
    (
        "config/backends/openai_codex.yaml.example",
        "config/schemas/openai_codex_backend.schema.yaml",
    ),
    (
        "config/tool_access_control_examples.yaml",
        "config/schemas/tool_call_reactor_config.schema.yaml",
    ),
]

print("Comprehensive config validation check:\n")

issues_found = False

for config_file, schema_file in config_schema_pairs:
    config_path = Path(config_file)
    schema_path = Path(schema_file)

    if not config_path.exists():
        print(f"[SKIP] {config_file} (config not found)")
        continue

    if not schema_path.exists():
        print(f"[SKIP] {config_file} (schema not found: {schema_file})")
        continue

    try:
        validate_yaml_against_schema(config_path, schema_path)
        print(f"[OK] {config_file}")
    except Exception as e:
        print(f"[FAIL] {config_file}")
        print(f"       Schema: {schema_file}")
        print(f"       Error: {str(e)[:300]}")
        issues_found = True

if not issues_found:
    print("\n[SUCCESS] All validated configs pass schema validation!")
else:
    print("\n[ISSUES FOUND] Some configs failed validation")
    sys.exit(1)
