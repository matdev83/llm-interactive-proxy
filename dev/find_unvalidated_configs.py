"""Find config files that aren't being validated."""

from pathlib import Path
import yaml

# List all config files
all_yaml_files = [
    'config/config.example.yaml',
    'config/codebuff.example.yaml',
    'config/qwen_backend.example.yaml',
    'config/identity_kilocode.example.yaml',
    'config/identity_factory_droid.example.yaml',
    'config/sso_auth.example.yaml',
    'config/reasoning_aliases.yaml.example',
    'config/tool_call_reactor_config.yaml',
    'config/edit_precision_model_temperatures.yaml',
    'config/edit_precision_patterns.yaml',
    'config/backends/openai_codex.yaml.example',
    'config/backends/openai_codex/backend.yaml',
    'config/backends/openai_codex/backend.example.yaml',
    'config/backends/gemini-cli-acp/backend.yaml',
    'config/backends/qwen-oauth/backend.yaml',
    'config/backends/zai/default_models.yaml',
]

# Configs that ARE being validated (from check_all_drift.py)
validated_in_drift_script = [
    'config/config.example.yaml',
    'config/codebuff.example.yaml',
    'config/qwen_backend.example.yaml',
    'config/identity_kilocode.example.yaml',
    'config/identity_factory_droid.example.yaml',
    'config/backends/openai_codex/backend.example.yaml',
    'config/edit_precision_patterns.yaml',
    'config/backends/zai/default_models.yaml',
    'config/edit_precision_model_temperatures.yaml',
]

# Configs validated in test_schema_drift.py
validated_in_tests = [
    'config/backends/openai_codex.yaml.example',
]

# Combined list of validated configs
validated = set(validated_in_drift_script + validated_in_tests)

print("Config files being validated:")
for f in validated:
    if Path(f).exists():
        print(f"  [OK] {f}")
    else:
        print(f"  [MISSING] {f}")

print("\nConfig files NOT being validated:")
for f in all_yaml_files:
    if f not in validated and Path(f).exists():
        print(f"  [UNVALIDATED] {f}")
