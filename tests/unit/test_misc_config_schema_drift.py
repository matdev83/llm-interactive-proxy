"""Test schema drift for empty_response, edit_precision, and rewriting configs.

This test validates that the app_config schema properly defines the fields
for these config sections, matching the Python model definitions.
"""

from pathlib import Path

from src.core.config.models.misc import EmptyResponseConfig
from src.core.config.models.rewriting import EditPrecisionConfig, RewritingConfig
from src.core.config.yaml_validation import validate_yaml_against_schema


class TestMiscConfigSchemaDrift:
    """Ensure misc config schemas match their Python models."""

    def test_empty_response_schema_has_all_code_fields(self):
        """Verify empty_response schema includes all fields from EmptyResponseConfig."""
        import yaml

        schema_path = Path("config/schemas/app_config.schema.yaml")
        with schema_path.open() as f:
            schema = yaml.safe_load(f)

        schema_fields = set(
            schema["properties"]["empty_response"]["properties"].keys()
        )
        code_fields = set(EmptyResponseConfig.model_fields.keys())

        missing = code_fields - schema_fields
        extra = schema_fields - code_fields

        assert not missing, f"Code model has fields not in schema: {missing}"
        assert not extra, f"Schema has fields not in code: {extra}"

    def test_edit_precision_schema_has_all_code_fields(self):
        """Verify edit_precision schema includes all fields from EditPrecisionConfig."""
        import yaml

        schema_path = Path("config/schemas/app_config.schema.yaml")
        with schema_path.open() as f:
            schema = yaml.safe_load(f)

        schema_fields = set(
            schema["properties"]["edit_precision"]["properties"].keys()
        )
        code_fields = set(EditPrecisionConfig.model_fields.keys())

        missing = code_fields - schema_fields
        extra = schema_fields - code_fields

        assert not missing, f"Code model has fields not in schema: {missing}"
        assert not extra, f"Schema has fields not in code: {extra}"

    def test_rewriting_schema_has_all_code_fields(self):
        """Verify rewriting schema includes all fields from RewritingConfig."""
        import yaml

        schema_path = Path("config/schemas/app_config.schema.yaml")
        with schema_path.open() as f:
            schema = yaml.safe_load(f)

        schema_fields = set(
            schema["properties"]["rewriting"]["properties"].keys()
        )
        code_fields = set(RewritingConfig.model_fields.keys())

        missing = code_fields - schema_fields
        extra = schema_fields - code_fields

        assert not missing, f"Code model has fields not in schema: {missing}"
        assert not extra, f"Schema has fields not in code: {extra}"

    def test_empty_response_config_validates(self):
        """Verify a valid empty_response config passes schema validation."""
        import tempfile

        schema_path = Path("config/schemas/app_config.schema.yaml")
        test_config = """
empty_response:
  enabled: true
  max_retries: 3
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(test_config)
            test_file = Path(f.name)

        try:
            validate_yaml_against_schema(test_file, schema_path)
        except Exception as e:
            raise AssertionError(
                f"Valid empty_response config failed validation: {e}"
            )
        finally:
            test_file.unlink()

    def test_edit_precision_config_validates(self):
        """Verify a valid edit_precision config passes schema validation."""
        import tempfile

        schema_path = Path("config/schemas/app_config.schema.yaml")
        test_config = """
edit_precision:
  enabled: true
  temperature: 0.1
  min_top_p: 0.3
  override_top_p: false
  override_top_k: false
  target_top_k: null
  exclude_agents_regex: null
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(test_config)
            test_file = Path(f.name)

        try:
            validate_yaml_against_schema(test_file, schema_path)
        except Exception as e:
            raise AssertionError(
                f"Valid edit_precision config failed validation: {e}"
            )
        finally:
            test_file.unlink()

    def test_rewriting_config_validates(self):
        """Verify a valid rewriting config passes schema validation."""
        import tempfile

        schema_path = Path("config/schemas/app_config.schema.yaml")
        test_config = """
rewriting:
  enabled: true
  config_path: "config/replacements"
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(test_config)
            test_file = Path(f.name)

        try:
            validate_yaml_against_schema(test_file, schema_path)
        except Exception as e:
            raise AssertionError(
                f"Valid rewriting config failed validation: {e}"
            )
        finally:
            test_file.unlink()
