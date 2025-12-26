#!/usr/bin/env python
"""Test all backend configs against schemas."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config.yaml_validation import validate_yaml_against_schema

backend_schemas = {
    "openai_codex": "config/schemas/openai_codex_backend.schema.yaml",
}

results = []

for backend_name, schema_path in backend_schemas.items():
    schema_file = Path(schema_path)
    if not schema_file.exists():
        print(f"[SKIP] Schema not found: {schema_path}")
        continue
    
    # Find all config files for this backend
    backend_dir = Path(f"config/backends/{backend_name}")
    if not backend_dir.exists():
        continue
    
    for config_file in backend_dir.glob("*.yaml"):
        if config_file.name.endswith(".example"):
            continue
        
        try:
            validate_yaml_against_schema(config_file, schema_file)
            results.append((backend_name, config_file.name, "OK"))
        except Exception as e:
            results.append((backend_name, config_file.name, f"FAIL: {str(e)[:100]}"))

for backend, name, status in results:
    print(f"[{backend}] {name}: {status}")
