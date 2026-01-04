"""Check for YAML keys that might not be in schemas."""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

# Load all config files
config_files = [
    "config/config.example.yaml",
    "config/codebuff.example.yaml",
    "config/qwen_backend.example.yaml",
    "config/identity_kilocode.example.yaml",
    "config/identity_factory_droid.example.yaml",
    "config/sso_auth.example.yaml",
]

for config_file in config_files:
    config_path = Path(config_file)
    if not config_path.exists():
        continue

    print(f"\n=== {config_file} ===")

    with config_path.open() as f:
        config = yaml.safe_load(f)

    def print_keys(d, prefix=""):
        for key, value in d.items():
            if isinstance(value, dict):
                print(f"{prefix}{key}")
                print_keys(value, prefix + "  ")
            elif isinstance(value, list) and value and isinstance(value[0], dict):
                print(f"{prefix}{key}:")
                print_keys(value[0], prefix + "  ")
            else:
                print(f"{prefix}{key}")

    print_keys(config)
