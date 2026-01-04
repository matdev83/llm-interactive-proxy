#!/usr/bin/env python
"""Check openai_codex schema drift in detail."""
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config.yaml_validation import validate_yaml_against_schema

# Test example file
example_path = Path("config/backends/openai_codex.yaml.example")
schema_path = Path("config/schemas/openai_codex_backend.schema.yaml")

print(f"Validating {example_path} against {schema_path}")
try:
    validate_yaml_against_schema(example_path, schema_path)
    print("[OK] Example file validates against schema")
except Exception as e:
    print(f"[FAIL] Example file validation failed: {e}")

# Test backend.yaml file
backend_path = Path("config/backends/openai_codex/backend.yaml")
print(f"\nValidating {backend_path} against {schema_path}")
try:
    validate_yaml_against_schema(backend_path, schema_path)
    print("[OK] Backend file validates against schema")
except Exception as e:
    print(f"[FAIL] Backend file validation failed: {e}")

# Load and inspect the schema
print("\n" + "=" * 60)
print("Schema structure:")
with schema_path.open() as f:
    schema = yaml.safe_load(f)

if "properties" in schema:
    print("Top-level properties:", list(schema["properties"].keys()))

    for prop, details in schema["properties"].items():
        print(f"\n{prop}:")
        if "properties" in details:
            print("  Sub-properties:", list(details["properties"].keys()))
        elif "items" in details and "properties" in details["items"]:
            print(
                "  Array items have properties:",
                list(details["items"]["properties"].keys()),
            )
