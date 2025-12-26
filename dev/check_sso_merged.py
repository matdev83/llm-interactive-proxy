#!/usr/bin/env python
"""Test validation of sso_auth.example.yaml when merged into full config."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config.yaml_validation import validate_yaml_against_schema

example_path = Path("config/sso_auth.example.yaml")
schema_path = Path("config/schemas/app_config.schema.yaml")

print(f"Validating {example_path} when merged into full app config...")

with example_path.open() as f:
    import yaml
    sso_config = yaml.safe_load(f)

# Create a minimal valid app config with the sso section from example
test_config = {
    "host": "127.0.0.1",
    "port": 8000,
    "sso": sso_config.get("sso", sso_config),  # Handle both formats
}

# Write to temp file
import tempfile
with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
    yaml.dump(test_config, f)
    temp_path = Path(f.name)

try:
    validate_yaml_against_schema(temp_path, schema_path)
    print("[OK] Validation passed! sso_auth.example.yaml is compatible with app_config schema.")
except Exception as e:
    print(f"[FAIL] Validation failed:")
    # Try to extract error details from ConfigurationError
    from src.core.common.exceptions import ConfigurationError
    if isinstance(e, ConfigurationError) and hasattr(e, 'details'):
        details = getattr(e, 'details', {})
        if 'errors' in details:
            for error in details['errors']:
                print(f"       {error}")
        else:
            print(f"       {e}")
    else:
        print(f"       {e}")
finally:
    temp_path.unlink()
