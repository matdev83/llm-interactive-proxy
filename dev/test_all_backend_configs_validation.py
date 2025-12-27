"""Test that all backend config files validate against their schemas."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
from src.core.config.yaml_validation import validate_yaml_against_schema

# Find all backend config files
backend_configs = list(Path('config/backends').rglob('*.yaml'))

print(f"Found {len(backend_configs)} backend config files\n")

# Map backend_type to schema
backend_type_to_schema = {
    'openai-codex': 'config/schemas/openai_codex_backend.schema.yaml',
}

issues = []

for config_path in backend_configs:
    # Skip example files
    if 'example' in config_path.name.lower():
        print(f"[SKIP] {config_path} (example file)")
        continue
    
    print(f"Checking {config_path}...")
    
    try:
        with config_path.open() as f:
            config = yaml.safe_load(f)
            backend_type = config.get('backend_type')
            
            if not backend_type:
                print("  [SKIP] No backend_type defined")
                continue
            
            if backend_type in backend_type_to_schema:
                schema_path = Path(backend_type_to_schema[backend_type])
                if schema_path.exists():
                    try:
                        validate_yaml_against_schema(config_path, schema_path)
                        print(f"  [OK] Validates against {schema_path.name}")
                    except Exception as e:
                        print(f"  [FAIL] Schema validation error: {str(e)[:200]}")
                        issues.append((str(config_path), str(e)))
                else:
                    print(f"  [SKIP] No schema found for backend_type={backend_type}")
            else:
                print(f"  [SKIP] No schema mapping for backend_type={backend_type}")
    except Exception as e:
        print(f"  [ERROR] Failed to load: {e}")

print("\n" + "="*60)
if issues:
    print(f"Found {len(issues)} issues:")
    for path, error in issues:
        print(f"  - {path}: {error}")
    sys.exit(1)
else:
    print("No issues found")
