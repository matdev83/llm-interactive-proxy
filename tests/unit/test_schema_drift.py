"""Test schema drift between YAML schemas and Python config models.

This test ensures that configuration schemas in config/schemas/ stay in sync
with the actual config models defined in Python code.
"""

from pathlib import Path

import yaml
from src.core.config.models.logging import LogLevel
from src.core.config.models.session import ToolCallReactorConfig
from src.core.config.yaml_validation import validate_yaml_against_schema


class TestSchemaDrift:
    """Ensure schemas match code models."""

    def test_logging_level_enum_includes_trace(self):
        """Verify schema supports TRACE level as defined in code constants."""
        schema_path = Path("config/schemas/app_config.schema.yaml")
        with schema_path.open() as f:
            schema = yaml.safe_load(f)

        level_enum = schema["properties"]["logging"]["properties"]["level"]["enum"]

        # All LogLevel enum values should be in schema
        for level in LogLevel:
            assert (
                level.value in level_enum
            ), f"LogLevel {level.value} missing from schema"

    def test_tool_call_reactor_schema_has_all_code_fields(self):
        """Verify tool_call_reactor schema includes all fields from code model."""
        schema_path = Path("config/schemas/tool_call_reactor_config.schema.yaml")
        with schema_path.open() as f:
            schema = yaml.safe_load(f)

        schema_fields = set(schema["properties"].keys())

        # Get fields from ToolCallReactorConfig model
        code_fields = set(ToolCallReactorConfig.model_fields.keys())

        # All code fields must be in schema
        missing = code_fields - schema_fields
        assert not missing, f"Code model has fields not in schema: {missing}"

    def test_trace_level_validates_in_schema(self):
        """Verify TRACE level is accepted by schema validation."""
        import tempfile

        schema_path = Path("config/schemas/app_config.schema.yaml")
        test_config = """
logging:
  level: "TRACE"
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(test_config)
            test_file = Path(f.name)

        try:
            validate_yaml_against_schema(test_file, schema_path)
        except Exception as e:
            raise AssertionError(f"TRACE level failed schema validation: {e}")
        finally:
            test_file.unlink()

    def test_tool_call_reactor_schema_accepts_all_config_fields(self):
        """Verify schema accepts a config with all known tool_call_reactor fields."""
        import tempfile

        schema_path = Path("config/schemas/tool_call_reactor_config.schema.yaml")

        # Config with all supported fields
        test_config = """
enabled: true
unified_steering_enabled: true
emit_legacy_steering_log: true
steering_policy_priorities:
  default: 100
steering_session_ttl_seconds: 1800
steering_max_sessions: 1024
apply_diff_steering_enabled: true
apply_diff_steering_rate_limit_seconds: 60
apply_diff_steering_message: "test message"
pytest_full_suite_steering_enabled: false
pytest_full_suite_steering_message: null
inline_python_steering_enabled: true
inline_python_steering_message: null
binary_file_edit_steering_enabled: true
binary_file_edit_steering_message: null
pytest_context_saving_enabled: false
fix_think_tags_enabled: false
test_execution_reminder_enabled: false
test_execution_reminder_message: null
steering_rules: []
access_policies: []
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(test_config)
            test_file = Path(f.name)

        try:
            validate_yaml_against_schema(test_file, schema_path)
        except Exception as e:
            raise AssertionError(
                f"Complete tool_call_reactor config failed validation: {e}"
            )
        finally:
            test_file.unlink()

    def test_example_configs_validate_against_schema(self):
        """Verify all example YAML configs validate against app_config schema."""
        schema_path = Path("config/schemas/app_config.schema.yaml")

        # Get all example config files
        example_configs = list(Path("config").glob("*.example.yaml"))

        for example_path in example_configs:
            try:
                validate_yaml_against_schema(example_path, schema_path)
            except Exception as e:
                raise AssertionError(
                    f"Example config {example_path.name} failed schema validation: {e}"
                )
