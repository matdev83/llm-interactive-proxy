#!/usr/bin/env python
"""Check edit_precision schema vs code model."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from src.core.config.models.rewriting import EditPrecisionConfig

with Path("config/schemas/app_config.schema.yaml").open() as f:
    app_schema = yaml.safe_load(f)

edit_precision_schema = app_schema.get("properties", {}).get("edit_precision", {})

print("Schema definition for edit_precision:")
print(yaml.dump(edit_precision_schema, default_flow_style=False))

print("\n" + "="*60)
print("EditPrecisionConfig model fields:")
for field_name, field_info in EditPrecisionConfig.model_fields.items():
    print(f"  {field_name}: {field_info.annotation} (default: {field_info.default})")
