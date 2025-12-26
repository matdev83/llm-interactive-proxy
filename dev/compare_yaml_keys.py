"""Compare YAML keys between example and schema."""

from pathlib import Path
import yaml
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config.yaml_validation import validate_yaml_against_schema

# Check reasoning_aliases.yaml.example
config_path = Path('config/reasoning_aliases.yaml.example')
schema_path = Path('config/schemas/reasoning_aliases.schema.yaml')

print("=== Checking reasoning_aliases.yaml.example ===\n")

# Load config
with config_path.open() as f:
    config = yaml.safe_load(f)

# Load schema
with schema_path.open() as f:
    schema = yaml.safe_load(f)

# Get schema properties
schema_props = set(schema.get('properties', {}).keys())

# Get config keys
config_keys = set(config.keys())

print(f"Config keys: {sorted(config_keys)}")
print(f"Schema properties: {sorted(schema_props)}")

missing = config_keys - schema_props
extra = schema_props - config_keys

if missing:
    print(f"\n[DRIFT] Config has keys NOT in schema: {sorted(missing)}")
if extra:
    print(f"[DRIFT] Schema has properties NOT in config: {sorted(extra)}")

# Try validating
try:
    validate_yaml_against_schema(config_path, schema_path)
    print("\n[OK] Schema validation passes")
except Exception as e:
    print(f"\n[FAIL] Schema validation: {e}")
