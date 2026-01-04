import sys

sys.path.insert(0, ".")

from pathlib import Path

from src.core.config.yaml_validation import validate_yaml_against_schema

config_path = Path("config/reasoning_aliases.yaml.example")
schema_path = Path("config/schemas/reasoning_aliases.schema.yaml")

try:
    validate_yaml_against_schema(config_path, schema_path)
    print("OK")
except Exception as e:
    print(f"FAIL: {e}")
