"""Validate zai default_models.yaml against its schema."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config.yaml_validation import validate_yaml_against_schema

config_path = Path('config/backends/zai/default_models.yaml')
schema_path = Path('config/schemas/zai_default_models.schema.yaml')

print(f"Validating {config_path} against {schema_path}...")

try:
    validate_yaml_against_schema(config_path, schema_path)
    print(f"[OK] {config_path} validates successfully")
except Exception as e:
    print(f"[FAIL] {config_path}")
    print(f"       Error: {e}")
