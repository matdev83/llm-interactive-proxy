from pathlib import Path
import sys
sys.path.insert(0, '.')
from src.core.config.yaml_validation import validate_yaml_against_schema

example_path = Path("config/sso_auth.example.yaml")
schema_path = Path("config/schemas/app_config.schema.yaml")

try:
    validate_yaml_against_schema(example_path, schema_path)
    print("SSO config validates successfully!")
except Exception as e:
    print(f"SSO config validation failed: {e}")
