#!/usr/bin/env python
"""Test validation of sso_auth.example.yaml against the schema."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config.yaml_validation import validate_yaml_against_schema

# sso_auth.example.yaml is loaded via --sso-config CLI flag
# It gets merged into config.sso section, so we need to test it against that schema

example_path = Path("config/sso_auth.example.yaml")
schema_path = Path("config/schemas/app_config.schema.yaml")

print(f"Validating {example_path} against app_config schema (sso section)...")

with example_path.open(encoding="utf-8") as f:
    import yaml

    sso_file_config = yaml.safe_load(f)

# Extract the sso section (or use the whole config if no 'sso' key)
# This matches the logic in auth_applicator._load_sso_config() line 170
sso_config = sso_file_config.get("sso", sso_file_config)

# Wrap the sso config in a structure that matches what the app expects
test_config = {"sso": sso_config}

# Write to temp file
import tempfile

with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
    yaml.dump(test_config, f)
    temp_path = Path(f.name)

try:
    validate_yaml_against_schema(temp_path, schema_path)
    print("[OK] Validation passed!")
except Exception as e:
    print("[FAIL] Validation failed:")
    # Try to extract error details from ConfigurationError
    from src.core.common.exceptions import ConfigurationError

    if isinstance(e, ConfigurationError) and hasattr(e, "details"):
        details = getattr(e, "details", {})
        if "errors" in details:
            for error in details["errors"]:
                print(f"       {error}")
        else:
            print(f"       {e}")
    else:
        print(f"       {e}")
finally:
    temp_path.unlink()
