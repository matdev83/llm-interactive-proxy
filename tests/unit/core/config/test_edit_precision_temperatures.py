from __future__ import annotations

from pathlib import Path

import pytest
from src.core.config import edit_precision_temperatures as temps
from src.core.config.edit_precision_temperatures import (
    EditPrecisionTemperaturesConfig,
    ModelTemperaturePattern,
    load_edit_precision_temperatures_config,
)


@pytest.fixture(autouse=True)
def reset_temperature_cache() -> None:
    temps._cached_config = None  # type: ignore[attr-defined]
    yield
    temps._cached_config = None  # type: ignore[attr-defined]


def test_get_temperature_for_model_matches_pattern() -> None:
    config = EditPrecisionTemperaturesConfig(
        default_temperature=0.1,
        model_patterns=[
            ModelTemperaturePattern(pattern="gpt", temperature=0.2),
            ModelTemperaturePattern(pattern="deepseek", temperature=0.0),
        ],
    )

    assert config.get_temperature_for_model("GPT-4") == pytest.approx(0.2)
    assert config.get_temperature_for_model("DeepSeek-coder") == pytest.approx(0.0)
    assert config.get_temperature_for_model("unknown-model") == pytest.approx(0.1)


def test_load_config_from_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "edit_precision.yaml"
    config_path.write_text(
        "default_temperature: 0.25\n"
        "model_patterns:\n"
        '  - pattern: "gpt"\n'
        "    temperature: 0.15\n",
        encoding="utf-8",
    )

    cfg = load_edit_precision_temperatures_config(
        config_path=config_path, force_reload=True
    )

    assert cfg.default_temperature == pytest.approx(0.25)
    assert cfg.get_temperature_for_model("gpt-4o") == pytest.approx(0.15)
    assert cfg.get_temperature_for_model("anthropic") == pytest.approx(0.25)


def test_load_missing_file_returns_default(tmp_path: Path) -> None:
    missing_path = tmp_path / "does_not_exist.yaml"

    cfg = load_edit_precision_temperatures_config(
        config_path=missing_path, force_reload=True
    )

    assert isinstance(cfg, EditPrecisionTemperaturesConfig)
    assert cfg.default_temperature == pytest.approx(0.0)
    assert cfg.model_patterns == []


def test_load_config_reloads_custom_path_without_cache(tmp_path: Path) -> None:
    config_path = tmp_path / "cached.yaml"
    config_path.write_text("default_temperature: 0.3\n", encoding="utf-8")

    first = load_edit_precision_temperatures_config(
        config_path=config_path, force_reload=True
    )
    assert first.default_temperature == pytest.approx(0.3)

    # Change on disk but expect cached result without force_reload
    config_path.write_text("default_temperature: 0.6\n", encoding="utf-8")

    cached = load_edit_precision_temperatures_config(config_path=config_path)
    assert cached.default_temperature == pytest.approx(0.6)


def test_load_config_returns_cached_instance_when_available() -> None:
    sentinel = EditPrecisionTemperaturesConfig(default_temperature=0.42)
    temps._cached_config = sentinel  # type: ignore[attr-defined]

    cfg = load_edit_precision_temperatures_config()
    assert cfg is sentinel
