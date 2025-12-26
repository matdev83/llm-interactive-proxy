#!/usr/bin/env python
"""Check openai_codex backend config drift."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config.yaml_validation import validate_yaml_against_schema

config_path = Path("config/backends/openai_codex/backend.yaml")
schema_path = Path("config/schemas/openai_codex_backend.schema.yaml")

try:
    validate_yaml_against_schema(config_path, schema_path)
    print("[OK] config validates against schema")
except Exception as e:
    print(f"[FAIL] {e}")
