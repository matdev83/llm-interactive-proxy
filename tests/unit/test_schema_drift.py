"""Test schema drift between YAML schemas and Python config models.

This test ensures that configuration schemas in config/schemas/ stay in sync
with the actual config models defined in Python code.
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import pytest
import yaml
from src.core.common.exceptions import ConfigurationError
from src.core.config.models.logging import LogLevel
from src.core.config.models.misc import UsageTrackingConfig
from src.core.config.models.session import ToolCallReactorConfig
from src.core.config.yaml_validation import validate_yaml_against_schema


def _calculate_file_hash(file_path: Path) -> str:
    """Calculate hash of a file for cache invalidation."""
    hasher = hashlib.md5()
    try:
        with file_path.open("rb") as f:
            hasher.update(f.read())
    except OSError:
        pass
    return hasher.hexdigest()


@pytest.fixture(scope="session")
def schema_validation_cache() -> dict[str, Any]:
    """Session-scoped cache for schema validation results."""
    project_root = Path(__file__).parent.parent
    schema_path = project_root / "config" / "schemas" / "app_config.schema.yaml"
    example_configs_dir = project_root / "config"
    cache_dir = project_root / ".pytest_cache"
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / "schema_validation_cache.json"

    cache: dict[str, Any] = {}
    if cache_file.exists():
        try:
            with cache_file.open(encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            cache = {}

    current_time = time.time()
    cache_timeout = 3600

    schema_hash = _calculate_file_hash(schema_path)
    example_config_hashes = {
        str(c): _calculate_file_hash(c)
        for c in example_configs_dir.glob("*.example.yaml")
    }

    combined_hashes = {"schema": schema_hash, "examples": example_config_hashes}

    if (
        cache.get("hashes") == combined_hashes
        and current_time - cache.get("timestamp", 0) < cache_timeout
        and "validation_results" in cache
    ):
        return cache

    validation_results = {}
    for example_path in example_configs_dir.glob("*.example.yaml"):
        try:
            validate_yaml_against_schema(example_path, schema_path)
            validation_results[str(example_path)] = "valid"
        except Exception as e:
            validation_results[str(example_path)] = f"error: {e!s}"

    cache.update(
        {
            "hashes": combined_hashes,
            "timestamp": current_time,
            "validation_results": validation_results,
        }
    )

    try:
        with cache_file.open("w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except OSError:
        pass

    return cache


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
steering_policy_priorities:
  default: 100
steering_session_ttl_seconds: 1800
steering_max_sessions: 1024
apply_diff_steering_enabled: true
apply_diff_steering_rate_limit_seconds: 60
apply_diff_steering_message: "test message"
pytest_full_suite_steering_enabled: false
pytest_full_suite_steering_message: null
cat_file_edits_steering_enabled: false
cat_file_edits_steering_message: null
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

    def test_example_configs_validate_against_schema(
        self, schema_validation_cache: dict[str, Any]
    ):
        """Verify all example YAML configs validate against app_config schema."""
        validation_results = schema_validation_cache.get("validation_results", {})

        project_root = Path(__file__).parent.parent
        example_configs = list((project_root / "config").glob("*.example.yaml"))

        for example_path in example_configs:
            result = validation_results.get(str(example_path))
            if result != "valid":
                if result and result.startswith("error:"):
                    error_msg = result[7:]
                else:
                    error_msg = "validation failed (cache stale)"
                raise AssertionError(
                    f"Example config {example_path.name} failed schema validation: {error_msg}"
                )

    def test_identity_config_validates_with_new_schema(self):
        """Verify identity configs with HeaderConfig structure validate."""
        import tempfile

        schema_path = Path("config/schemas/app_config.schema.yaml")

        # Test identity config with override mode (like identity_kilocode.example.yaml)
        test_config = """
identity:
  user_agent:
    mode: override
    override_value: "Kilo-Code/4.122.1"
  url:
    mode: override
    override_value: "https://kilocode.com"
  title:
    mode: override
    override_value: "Kilo Code"
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(test_config)
            test_file = Path(f.name)

        try:
            validate_yaml_against_schema(test_file, schema_path)
        except Exception as e:
            raise AssertionError(
                f"Identity config with override mode failed validation: {e}"
            )
        finally:
            test_file.unlink()

    def test_dynamic_compression_methods_reject_non_boolean_in_schema(self):
        """YAML must not advertise string method toggles the Python model cannot load."""
        import tempfile

        schema_path = Path("config/schemas/app_config.schema.yaml")
        test_config = """
dynamic_compression:
  methods:
    pytest_failure_focus: inherit_legacy
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(test_config)
            test_file = Path(f.name)

        try:
            with pytest.raises(ConfigurationError) as exc_info:
                validate_yaml_against_schema(test_file, schema_path)
            details = exc_info.value.details or {}
            errors = details.get("errors") or []
            joined = " ".join(str(e) for e in errors)
            assert "boolean" in joined.lower()
        finally:
            test_file.unlink()

    def test_reasoning_aliases_config_validates_with_new_schema(self):
        """Verify reasoning_aliases config with reasoning_alias_settings validates."""
        import tempfile

        schema_path = Path("config/schemas/app_config.schema.yaml")

        test_config = """
reasoning_aliases:
  reasoning_alias_settings:
    - model: "claude-sonnet-4"
      modes:
        low:
          max_reasoning_tokens: 2048
          reasoning_effort: "low"
        medium:
          max_reasoning_tokens: 8192
          reasoning_effort: "medium"
        high:
          max_reasoning_tokens: 32768
          reasoning_effort: "high"
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(test_config)
            test_file = Path(f.name)

        try:
            validate_yaml_against_schema(test_file, schema_path)
        except Exception as e:
            raise AssertionError(f"Reasoning aliases config failed validation: {e}")
        finally:
            test_file.unlink()

    def test_usage_tracking_schema_matches_code_fields(self):
        """Verify usage_tracking schema only contains fields present in UsageTrackingConfig."""
        schema_path = Path("config/schemas/app_config.schema.yaml")
        with schema_path.open() as f:
            schema = yaml.safe_load(f)

        schema_fields = set(schema["properties"]["usage_tracking"]["properties"].keys())
        code_fields = set(UsageTrackingConfig.model_fields.keys())

        extra_in_schema = schema_fields - code_fields
        missing_in_schema = code_fields - schema_fields

        assert not extra_in_schema, f"Schema has fields not in code: {extra_in_schema}"
        assert (
            not missing_in_schema
        ), f"Code has fields not in schema: {missing_in_schema}"

    def test_openai_codex_backend_example_validates(self):
        """Verify openai_codex.yaml.example validates against its schema."""
        example_path = Path("config/backends/openai_codex.yaml.example")
        schema_path = Path("config/schemas/openai_codex_backend.schema.yaml")

        if not example_path.exists():
            raise AssertionError(f"Example file not found: {example_path}")

        try:
            validate_yaml_against_schema(example_path, schema_path)
        except Exception as e:
            raise AssertionError(
                f"openai_codex.yaml.example failed schema validation: {e}"
            )

    def test_openai_codex_v2_backend_example_validates(self):
        """Verify openai_codex_v2 backend.example validates against its schema."""
        example_path = Path("config/backends/openai_codex_v2/backend.example.yaml")
        schema_path = Path("config/schemas/openai_codex_v2_backend.schema.yaml")

        if not example_path.exists():
            raise AssertionError(f"Example file not found: {example_path}")

        try:
            validate_yaml_against_schema(example_path, schema_path)
        except Exception as e:
            raise AssertionError(
                f"openai_codex_v2 backend.example failed schema validation: {e}"
            )

    def test_health_check_schema_matches_code_fields(self):
        """Verify health_check schema includes all fields from HealthCheckConfig."""
        schema_path = Path("config/schemas/health_check.yaml")
        with schema_path.open() as f:
            schema = yaml.safe_load(f)

        schema_fields = set(schema["properties"].keys())

        from src.core.domain.configuration.health_check_config import (
            HealthCheckConfig,
        )

        code_fields = set(HealthCheckConfig.model_fields.keys())

        missing_in_schema = code_fields - schema_fields
        extra_in_schema = schema_fields - code_fields

        assert (
            not missing_in_schema
        ), f"Code model has fields not in schema: {missing_in_schema}"
        assert not extra_in_schema, f"Schema has fields not in code: {extra_in_schema}"
