# Generate a detailed drift report
from pathlib import Path

import yaml

# Check schema existence for all backend configs
backend_configs = {
    "config/backends/openai_codex/backend.yaml": "openai-codex",
    "config/backends/qwen-oauth/backend.yaml": "qwen-oauth",
}

print("=== BACKEND CONFIG SCHEMA COVERAGE ===\n")

for config_path, backend_name in backend_configs.items():
    cp = Path(config_path)
    if not cp.exists():
        print(f"SKIP: {config_path} (not found)")
        continue

    # Check if a schema exists
    schema_name = f"config/schemas/{backend_name.replace('-', '_')}_backend.schema.yaml"
    schema_path = Path(schema_name)

    if schema_path.exists():
        print(f"OK: {backend_name} has schema: {schema_name}")
    else:
        print(f"MISSING: {backend_name} has no schema file")
        print(f"  Config file: {config_path}")

        # Check what fields are in the config
        with cp.open() as f:
            config_data = yaml.safe_load(f)

        if isinstance(config_data, dict):
            print(f"  Fields in config: {', '.join(config_data.keys())}")
