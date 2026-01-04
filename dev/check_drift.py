#!/usr/bin/env python
"""Quick script to identify schema drift in example configs."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config.yaml_validation import validate_yaml_against_schema

schema_path = Path("config/schemas/app_config.schema.yaml")

example_configs = [
    "config/config.example.yaml",
    "config/codebuff.example.yaml",
    "config/qwen_backend.example.yaml",
    "config/identity_kilocode.example.yaml",
    "config/identity_factory_droid.example.yaml",
]

print("Checking drift between example configs and app_config schema:\n")

for config_path_str in example_configs:
    config_path = Path(config_path_str)
    if not config_path.exists():
        print(f"❌ {config_path.name}: File not found")
        continue

    try:
        validate_yaml_against_schema(config_path, schema_path)
        print(f"[OK] {config_path.name}")
    except Exception as e:
        print(f"[FAIL] {config_path.name}: {str(e)[:200]}")

print(
    "\nNote: sso_auth.example.yaml is not tested here as it uses --sso-config CLI flag."
)
