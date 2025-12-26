from pathlib import Path
import sys
import yaml
sys.path.insert(0, '.')
from src.core.config.yaml_validation import validate_yaml_against_schema

# Check for example YAMLs that should validate against app_config.schema.yaml
app_config_schema = Path("config/schemas/app_config.schema.yaml")
example_configs = [
    "config/codebuff.example.yaml",
    "config/identity_factory_droid.example.yaml",
    "config/identity_kilocode.example.yaml",
    "config/qwen_backend.example.yaml",
]

print("=== Checking example configs against app_config schema ===\n")
all_pass = True

for config_path in example_configs:
    p = Path(config_path)
    if not p.exists():
        print(f"SKIP (not found): {config_path}")
        continue
    
    try:
        validate_yaml_against_schema(p, app_config_schema)
        print(f"PASS: {config_path}")
    except Exception as e:
        print(f"FAIL: {config_path}")
        print(f"  Error: {e}")
        all_pass = False

if all_pass:
    print("\n=== All example configs validate successfully ===")

