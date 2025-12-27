# Test if backend configs would work with BackendConfig model
import sys
from pathlib import Path

sys.path.insert(0, '.')
import yaml
from src.core.config.models.backends import BackendConfig

backend_configs = [
    "config/backends/gemini-cli-acp/backend.yaml",
    "config/backends/qwen-oauth/backend.yaml",
]

print("=== Testing backend configs with BackendConfig model ===\n")

for config_path in backend_configs:
    p = Path(config_path)
    if not p.exists():
        print(f"SKIP (not found): {config_path}")
        continue
    
    print(f"Testing: {p.name}")
    try:
        with p.open() as f:
            config_data = yaml.safe_load(f)
        
        # Try to create BackendConfig from this data
        backend_config = BackendConfig(**config_data)
        print("  PASS: BackendConfig created successfully")
        print(f"  api_key: {backend_config.api_key}")
        print(f"  timeout: {backend_config.timeout}")
        print(f"  extra fields: {list(backend_config.extra.keys())}")
    except Exception as e:
        print(f"  FAIL: {e}")
    print()

