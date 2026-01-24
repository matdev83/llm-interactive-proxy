
from pathlib import Path
from src.core.config.app_config import AppConfig
from src.core.domain.configuration.sandboxing_config import SandboxingConfiguration
import yaml

config = AppConfig(
    sandboxing=SandboxingConfiguration(
        enabled=True,
        strict_mode=True,
        allow_parent_access=False,
        custom_tool_patterns=["custom_.*"],
    )
)
if not config.backends.openai.api_key:
    object.__setattr__(config.backends.openai, "api_key", "test-key")

config_path = Path("debug_config.yaml")
config.save(config_path)

with open(config_path, "r") as f:
    print(yaml.safe_load(f))

from src.core.config.yaml_validation import validate_yaml_against_schema
schema_path = Path("config/schemas/app_config.schema.yaml")
try:
    validate_yaml_against_schema(config_path, schema_path)
    print("Validation successful")
except Exception as e:
    print(f"Validation failed: {e}")
    if hasattr(e, "details") and "errors" in e.details:
        for err in e.details["errors"]:
            print(f"  - {err}")
