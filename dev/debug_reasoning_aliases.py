"""Debug reasoning_aliases.yaml.example validation."""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config.yaml_validation import validate_yaml_against_schema

config_path = Path('config/reasoning_aliases.yaml.example')
schema_path = Path('config/schemas/reasoning_aliases.schema.yaml')

print("Loading config...")
with config_path.open() as f:
    config = yaml.safe_load(f)

print("Config loaded:")
print(yaml.dump(config, default_flow_style=False))

print("\nLoading schema...")
with schema_path.open() as f:
    schema = yaml.safe_load(f)

print("Schema:")
print(yaml.dump(schema, default_flow_style=False))

print("\nValidating...")
try:
    validate_yaml_against_schema(config_path, schema_path)
    print("[OK] Validation passed")
except Exception as e:
    print(f"[FAIL] {e}")
    import traceback
    traceback.print_exc()
