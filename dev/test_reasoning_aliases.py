from pathlib import Path
import sys
sys.path.insert(0, '.')
from src.core.config.yaml_validation import validate_yaml_against_schema

# Test reasoning_aliases.yaml.example against its schema
example_path = Path("config/reasoning_aliases.yaml.example")
schema_path = Path("config/schemas/reasoning_aliases.schema.yaml")

print("Testing config/reasoning_aliases.yaml.example...")
try:
    validate_yaml_against_schema(example_path, schema_path)
    print("PASS: Validates successfully!")
except Exception as e:
    print(f"FAIL: {e}")

# Also test against app_config schema (since reasoning_aliases might be nested there)
app_schema = Path("config/schemas/app_config.schema.yaml")
print("\nTesting config/reasoning_aliases.yaml.example against app_config schema...")
try:
    import yaml
    with example_path.open() as f:
        example_data = yaml.safe_load(f)
    
    # Create a minimal config with the reasoning_aliases section
    test_config = {"reasoning_aliases": example_data}
    
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(test_config, f)
        test_file = Path(f.name)
    
    try:
        validate_yaml_against_schema(test_file, app_schema)
        print("PASS: Validates against app_config schema!")
    finally:
        test_file.unlink()
except Exception as e:
    print(f"FAIL: {e}")

