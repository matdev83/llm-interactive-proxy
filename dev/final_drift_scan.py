import sys
from pathlib import Path

import yaml

sys.path.insert(0, '.')
from src.core.config.yaml_validation import validate_yaml_against_schema

# Comprehensive drift scan
print("=== COMPREHENSIVE CONFIG DRIFT SCAN ===\n")

# 1. Example configs against app_config schema
print("1. Example configs against app_config.schema.yaml:")
print("-" * 60)
app_schema = Path("config/schemas/app_config.schema.yaml")
example_configs = [
    "config/codebuff.example.yaml",
    "config/identity_factory_droid.example.yaml",
    "config/identity_kilocode.example.yaml",
    "config/qwen_backend.example.yaml",
    "config/sso_auth.example.yaml",
]
for config_path in example_configs:
    p = Path(config_path)
    if not p.exists():
        print(f"  SKIP (not found): {config_path}")
        continue
    try:
        validate_yaml_against_schema(p, app_schema)
        print(f"  PASS: {p.name}")
    except Exception as e:
        print(f"  FAIL: {p.name}")
        print(f"    {str(e)[:100]}")

# 2. Edit precision configs
print("\n2. Edit precision configs:")
print("-" * 60)
edit_configs = [
    ("config/edit_precision_patterns.yaml", "config/schemas/edit_precision_patterns.schema.yaml"),
    ("config/edit_precision_model_temperatures.yaml", "config/schemas/edit_precision_temperatures.schema.yaml"),
]
for config_path, schema_path in edit_configs:
    cp, sp = Path(config_path), Path(schema_path)
    if not cp.exists():
        print(f"  SKIP (not found): {config_path}")
        continue
    try:
        validate_yaml_against_schema(cp, sp)
        print(f"  PASS: {cp.name}")
    except Exception as e:
        print(f"  FAIL: {cp.name}")
        print(f"    {str(e)[:100]}")

# 3. ZAI default models
print("\n3. ZAI default models:")
print("-" * 60)
zai_config = Path("config/backends/zai/default_models.yaml")
zai_schema = Path("config/schemas/zai_default_models.schema.yaml")
if zai_config.exists() and zai_schema.exists():
    try:
        validate_yaml_against_schema(zai_config, zai_schema)
        print(f"  PASS: {zai_config.name}")
    except Exception as e:
        print(f"  FAIL: {zai_config.name}")
        print(f"    {str(e)[:100]}")
else:
    print("  SKIP: config or schema not found")

# 4. Tool call reactor configs
print("\n4. Tool call reactor configs:")
print("-" * 60)
tool_configs = [
    "config/tool_call_reactor_config.yaml",
    "config/tool_access_control_examples.yaml",
]
tool_schema = Path("config/schemas/tool_call_reactor_config.schema.yaml")
for config_path in tool_configs:
    cp = Path(config_path)
    if not cp.exists():
        print(f"  SKIP (not found): {config_path}")
        continue
    try:
        validate_yaml_against_schema(cp, tool_schema)
        print(f"  PASS: {cp.name}")
    except Exception as e:
        print(f"  FAIL: {cp.name}")
        print(f"    {str(e)[:100]}")

# 5. Reasoning aliases
print("\n5. Reasoning aliases:")
print("-" * 60)
reasoning_config = Path("config/reasoning_aliases.yaml.example")
reasoning_schema = Path("config/schemas/reasoning_aliases.schema.yaml")
if reasoning_config.exists() and reasoning_schema.exists():
    try:
        validate_yaml_against_schema(reasoning_config, reasoning_schema)
        print(f"  PASS: {reasoning_config.name}")
    except Exception as e:
        print(f"  FAIL: {reasoning_config.name}")
        print(f"    {str(e)[:100]}")
else:
    print("  SKIP: config or schema not found")

# 6. OpenAI Codex backend configs
print("\n6. OpenAI Codex backend configs:")
print("-" * 60)
codex_configs = [
    "config/backends/openai_codex/backend.example.yaml",
    "config/backends/openai_codex.yaml.example",
]
codex_schema = Path("config/schemas/openai_codex_backend.schema.yaml")
for config_path in codex_configs:
    cp = Path(config_path)
    if not cp.exists():
        print(f"  SKIP (not found): {config_path}")
        continue
    try:
        validate_yaml_against_schema(cp, codex_schema)
        print(f"  PASS: {cp.name}")
    except Exception as e:
        print(f"  FAIL: {cp.name}")
        print(f"    {str(e)[:100]}")

# 7. Backend configs without schemas
print("\n7. Backend configs (no schema - just checking YAML validity):")
print("-" * 60)
backend_configs = [
    "config/backends/gemini-cli-acp/backend.yaml",
    "config/backends/openai_codex/backend.yaml",
    "config/backends/qwen-oauth/backend.yaml",
]
for config_path in backend_configs:
    cp = Path(config_path)
    if not cp.exists():
        print(f"  SKIP (not found): {config_path}")
        continue
    try:
        with cp.open() as f:
            yaml.safe_load(f)
        print(f"  OK (valid YAML): {cp.name}")
    except Exception as e:
        print(f"  FAIL (invalid YAML): {cp.name}")
        print(f"    {str(e)[:100]}")

print("\n=== SCAN COMPLETE ===")

