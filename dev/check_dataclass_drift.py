#!/usr/bin/env python
"""Check for drift between dataclass configs and schemas."""
import sys
from pathlib import Path
from dataclasses import fields

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from src.core.domain.configuration.compaction_config import CompactionConfig
from src.core.domain.configuration.assessment_config import AssessmentConfig


def check_dataclass_vs_schema(dataclass_class, schema_path, schema_section):
    """Compare dataclass fields with schema fields."""
    schema_file = Path(schema_path)
    with schema_file.open() as f:
        schema = yaml.safe_load(f)
    
    schema_section_obj = schema.get("properties", {}).get(schema_section, {})
    schema_props = schema_section_obj.get("properties", {})
    if not schema_props:
        schema_props = schema_section_obj
    
    dataclass_fields = {f.name for f in fields(dataclass_class)}
    schema_fields = set(schema_props.keys()) if isinstance(schema_props, dict) else set()
    
    missing_in_schema = dataclass_fields - schema_fields
    extra_in_schema = schema_fields - dataclass_fields
    
    print(f"\n{dataclass_class.__name__} ({schema_section}):")
    if missing_in_schema:
        print(f"  MISSING in schema: {sorted(missing_in_schema)}")
    if extra_in_schema:
        print(f"  EXTRA in schema: {sorted(extra_in_schema)}")
    if not missing_in_schema and not extra_in_schema:
        print(f"  [OK] Fields match")
    
    return len(missing_in_schema) == 0 and len(extra_in_schema) == 0


def main():
    checks = [
        (CompactionConfig, "config/schemas/app_config.schema.yaml", "compaction"),
        (AssessmentConfig, "config/schemas/app_config.schema.yaml", "assessment"),
    ]
    
    all_ok = True
    for model, schema_path, section in checks:
        if not check_dataclass_vs_schema(model, schema_path, section):
            all_ok = False
    
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
