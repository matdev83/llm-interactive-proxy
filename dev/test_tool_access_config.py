import sys
from pathlib import Path

sys.path.insert(0, ".")
from src.core.config.yaml_validation import validate_yaml_against_schema

# Test tool_access_control_examples.yaml
example_path = Path("config/tool_access_control_examples.yaml")
schema_path = Path("config/schemas/tool_call_reactor_config.schema.yaml")

print("Testing config/tool_access_control_examples.yaml...")
try:
    validate_yaml_against_schema(example_path, schema_path)
    print("PASS: Validates successfully!")
except Exception as e:
    print(f"FAIL: {e}")

# Test tool_call_reactor_config.yaml
config_path = Path("config/tool_call_reactor_config.yaml")
print("\nTesting config/tool_call_reactor_config.yaml...")
try:
    validate_yaml_against_schema(config_path, schema_path)
    print("PASS: Validates successfully!")
except Exception as e:
    print(f"FAIL: {e}")
