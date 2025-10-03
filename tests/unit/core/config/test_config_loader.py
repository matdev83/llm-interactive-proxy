from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from src.core.config.config_loader import ConfigLoader


@pytest.fixture
def config_loader():
    return ConfigLoader()


@pytest.fixture
def reasoning_aliases_file(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    file_path = config_dir / "reasoning_aliases.yaml"
    return file_path


def test_load_reasoning_aliases_config_success(
    config_loader: ConfigLoader, reasoning_aliases_file: Path
):
    valid_config = {
        "reasoning_alias_settings": [
            {
                "model": "claude-3-opus-20240229",
                "modes": {
                    "test": {
                        "max_reasoning_tokens": 1024,
                        "reasoning_effort": "auto",
                    }
                },
            }
        ]
    }
    reasoning_aliases_file.write_text(yaml.dump(valid_config))

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch(
            "pathlib.Path.read_text", return_value=reasoning_aliases_file.read_text()
        ),
    ):
        config = config_loader._load_reasoning_aliases_config()
        assert "reasoning_alias_settings" in config
        assert len(config["reasoning_alias_settings"]) == 1
        assert (
            config["reasoning_alias_settings"][0]["model"] == "claude-3-opus-20240229"
        )


def test_load_reasoning_aliases_config_invalid_yaml(
    config_loader: ConfigLoader, reasoning_aliases_file: Path
):
    reasoning_aliases_file.write_text("invalid: yaml: here")

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch(
            "pathlib.Path.read_text", return_value=reasoning_aliases_file.read_text()
        ),
        pytest.raises(ValueError, match="Invalid YAML"),
    ):
        config_loader._load_reasoning_aliases_config()


def test_load_reasoning_aliases_config_validation_error(
    config_loader: ConfigLoader, reasoning_aliases_file: Path
):
    # Test with a missing 'model' field, which should trigger a validation error
    invalid_config = {
        "reasoning_alias_settings": [
            {
                "model": "claude-3-opus-20240229",
                "modes": {
                    "test-invalid": {
                        "max_reasoning_tokens": "invalid-token-type",
                    }
                },
            }
        ]
    }
    reasoning_aliases_file.write_text(yaml.dump(invalid_config))

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch(
            "pathlib.Path.read_text", return_value=reasoning_aliases_file.read_text()
        ),
        pytest.raises(ValueError, match="Invalid reasoning aliases config"),
    ):
        config_loader._load_reasoning_aliases_config()


def test_load_reasoning_aliases_config_file_not_found(config_loader: ConfigLoader):
    with patch("pathlib.Path.exists", return_value=False):
        config = config_loader._load_reasoning_aliases_config()
        assert config == {}
