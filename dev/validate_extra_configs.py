from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config.yaml_validation import validate_yaml_against_schema

files_and_schemas = [
    ('config/tool_call_reactor_config.yaml', 'tool_call_reactor_config'),
    ('config/edit_precision_model_temperatures.yaml', 'edit_precision_temperatures'),
    ('config/edit_precision_patterns.yaml', 'edit_precision_patterns'),
    ('config/reasoning_aliases.yaml.example', 'reasoning_aliases'),
    ('config/identity_factory_droid.example.yaml', 'app_config'),
    ('config/identity_kilocode.example.yaml', 'app_config'),
    ('config/sso_auth.example.yaml', 'app_config'),
]

for config_file, schema_name in files_and_schemas:
    config_path = Path(config_file)
    schema_path = Path(f'config/schemas/{schema_name}.schema.yaml')
    
    if not config_path.exists():
        print(f'[SKIP] {config_file} (file not found)')
        continue
    if not schema_path.exists():
        print(f'[SKIP] {config_file} (schema not found: {schema_path})')
        continue
    
    print(f'Validating {config_file} against {schema_path}...')
    try:
        validate_yaml_against_schema(config_path, schema_path)
        print(f'  [OK] {config_file}')
    except Exception as e:
        print(f'  [FAIL] {config_file}: {str(e)[:200]}')
