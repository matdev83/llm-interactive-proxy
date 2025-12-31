import sys
from pathlib import Path

sys.path.insert(0, ".")

import yaml
from src.core.config.yaml_validation import validate_yaml_against_schema

backend_configs = [
    "config/backends/openai_codex/backend.yaml",
    "config/backends/openai_codex/backend.example.yaml",
    "config/backends/openai_codex.yaml.example",
    "config/backends/qwen-oauth/backend.yaml",
    "config/backends/zai/default_models.yaml",
]

# Check if we have schemas for these
schema_files = {
    "config/backends/openai_codex.yaml.example": "config/schemas/openai_codex_backend.schema.yaml",
    "config/backends/openai_codex/backend.example.yaml": "config/schemas/openai_codex_backend.schema.yaml",
}

for config_path in backend_configs:
    p = Path(config_path)
    if not p.exists():
        print(f"SKIP (not found): {config_path}")
        continue

    if config_path in schema_files:
        schema_p = Path(schema_files[config_path])
        try:
            validate_yaml_against_schema(p, schema_p)
            print(f"PASS: {config_path}")
        except Exception as e:
            print(f"FAIL: {config_path}")
            print(f"  Error: {e}")
    else:
        # Just check if it loads as valid YAML
        try:
            with p.open() as f:
                data = yaml.safe_load(f)
            print(f"OK (YAML only, no schema): {config_path}")
        except Exception as e:
            print(f"FAIL (invalid YAML): {config_path}")
            print(f"  Error: {e}")
