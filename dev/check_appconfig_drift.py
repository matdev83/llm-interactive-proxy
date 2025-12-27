#!/usr/bin/env python
"""Check for missing fields in schema compared to config models."""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

# Load schema
schema_path = Path("config/schemas/app_config.schema.yaml")
with schema_path.open() as f:
    schema = yaml.safe_load(f)

# Get all properties from schema
schema_props = set(schema.get("properties", {}).keys())

print("Schema properties (top-level):")
for p in sorted(schema_props):
    print(f"  - {p}")

# Check AppConfigModel
from src.core.config.models.app_config_model import AppConfigModel

model_fields = set(AppConfigModel.model_fields.keys())

print("\nAppConfigModel fields:")
for f in sorted(model_fields):
    print(f"  - {f}")

# Compare
print("\nComparing model vs schema:")
missing_in_schema = model_fields - schema_props
missing_in_model = schema_props - model_fields

if missing_in_schema:
    print(f"\n  Model fields NOT in schema: {sorted(missing_in_schema)}")
if missing_in_model:
    print(f"\n  Schema fields NOT in model: {sorted(missing_in_model)}")

if not missing_in_schema and not missing_in_model:
    print("\n  [OK] All fields match at top level!")

# Check nested structures
print("\n\nChecking nested structures:\n")

# Codebuff config
from src.core.config.models.misc import CodebuffConfig

codebuff_fields = set(CodebuffConfig.model_fields.keys())
print(f"CodebuffConfig model fields: {sorted(codebuff_fields)}")

codebuff_schema_props = set(schema.get("properties", {}).get("codebuff", {}).get("properties", {}).keys())
print(f"Codebuff schema properties: {sorted(codebuff_schema_props)}")

missing_cb_schema = codebuff_fields - codebuff_schema_props
missing_cb_model = codebuff_schema_props - codebuff_fields

if missing_cb_schema:
    print(f"\n  Codebuff model fields NOT in schema: {sorted(missing_cb_schema)}")
if missing_cb_model:
    print(f"\n  Codebuff schema fields NOT in model: {sorted(missing_cb_model)}")

if not missing_cb_schema and not missing_cb_model:
    print("\n  [OK] All codebuff fields match!")
