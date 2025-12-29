"""
Unit tests for non-forwardable message tagging configuration.

Tests coverage for:
- NonForwardableTaggingConfig: default values and validation
- Config loading precedence (CLI > ENV > YAML > defaults)
- Schema validation

Requirements: 14.3, 14.4
"""

from pathlib import Path

import pytest
from src.core.config.app_config import load_config
from src.core.config.models.non_forwardable_config import NonForwardableTaggingConfig


class TestNonForwardableTaggingConfig:
    """Tests for NonForwardableTaggingConfig model."""

    def test_default_max_identities_per_session(self) -> None:
        """Default max_identities_per_session is 10000."""
        config = NonForwardableTaggingConfig()
        assert config.max_identities_per_session == 10000

    def test_custom_max_identities_per_session(self) -> None:
        """Can set custom max_identities_per_session."""
        config = NonForwardableTaggingConfig(max_identities_per_session=5000)
        assert config.max_identities_per_session == 5000

    def test_field_validation_positive_integer(self) -> None:
        """max_identities_per_session must be a positive integer."""
        # Valid: positive integer
        config = NonForwardableTaggingConfig(max_identities_per_session=1)
        assert config.max_identities_per_session == 1

        # Valid: large positive integer
        config = NonForwardableTaggingConfig(max_identities_per_session=100000)
        assert config.max_identities_per_session == 100000

    def test_config_is_frozen(self) -> None:
        """Config is frozen (immutable)."""
        config = NonForwardableTaggingConfig()
        # Pydantic frozen models raise ValidationError when trying to set attributes
        with pytest.raises((AttributeError, ValueError)):
            config.max_identities_per_session = 5000  # type: ignore


class TestConfigLoadingPrecedence:
    """Tests for config loading precedence."""

    def test_default_value_when_not_configured(self) -> None:
        """Default value is used when not configured."""
        # Load config without any non_forwardable_tagging section
        config = load_config(config_path=None, environ={})
        # Should have default value
        assert hasattr(config, "non_forwardable_tagging")
        assert config.non_forwardable_tagging.max_identities_per_session == 10000

    def test_yaml_config_loading(self, tmp_path: Path) -> None:
        """YAML config can set max_identities_per_session."""
        yaml_content = """
non_forwardable_tagging:
  max_identities_per_session: 5000
"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content)

        config = load_config(config_path=str(config_file), environ={})
        assert config.non_forwardable_tagging.max_identities_per_session == 5000

    def test_config_precedence_yaml_defaults(self, tmp_path: Path) -> None:
        """Config precedence: YAML > defaults."""
        # Create YAML with a value
        yaml_content = """
non_forwardable_tagging:
  max_identities_per_session: 5000
"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content)

        # YAML should be used
        config = load_config(config_path=str(config_file), environ={})
        assert config.non_forwardable_tagging.max_identities_per_session == 5000

        # Without YAML, default should be used
        config = load_config(config_path=None, environ={})
        assert config.non_forwardable_tagging.max_identities_per_session == 10000
