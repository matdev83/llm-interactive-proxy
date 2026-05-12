from __future__ import annotations

from pathlib import Path

from src.core.config.env.from_env_part2 import apply_config_part2
from src.core.config.models.backends import (
    DEFAULT_INTERLEAVED_THINKING_INSTRUCTIONS_FILE,
    BackendSettings,
)
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource


def test_backend_settings_default_interleaved_thinking_instructions_file_points_to_shipped_prompt() -> (
    None
):
    settings = BackendSettings()

    assert (
        settings.interleaved_thinking_instructions_file
        == DEFAULT_INTERLEAVED_THINKING_INSTRUCTIONS_FILE
    )
    prompt_path = Path(settings.interleaved_thinking_instructions_file)
    assert prompt_path.is_file()
    prompt = prompt_path.read_text(encoding="utf-8")
    assert "<proxy_thinker_memo>" in prompt


def test_env_loader_defaults_interleaved_thinking_instructions_file_to_shipped_prompt() -> (
    None
):
    config: dict[str, object] = {}
    resolution = ParameterResolution()

    apply_config_part2(config, {}, resolution)

    backends = config["backends"]
    assert isinstance(backends, dict)
    assert (
        backends["interleaved_thinking_instructions_file"]
        == DEFAULT_INTERLEAVED_THINKING_INSTRUCTIONS_FILE
    )
    assert not resolution.is_set("backends.interleaved_thinking_instructions_file")


def test_backend_settings_accepts_interleaved_thinking_instructions_file() -> None:
    settings = BackendSettings(
        interleaved_thinking_instructions_file="config/prompts/thinker.md"
    )

    assert (
        settings.interleaved_thinking_instructions_file == "config/prompts/thinker.md"
    )


def test_env_loader_reads_interleaved_thinking_instructions_file() -> None:
    config: dict[str, object] = {}
    resolution = ParameterResolution()

    apply_config_part2(
        config,
        {"INTERLEAVED_THINKING_INSTRUCTIONS_FILE": "config/prompts/thinker.md"},
        resolution,
    )

    backends = config["backends"]
    assert isinstance(backends, dict)
    assert (
        backends["interleaved_thinking_instructions_file"]
        == "config/prompts/thinker.md"
    )
    assert resolution.is_set("backends.interleaved_thinking_instructions_file")
    env_params = resolution.latest_by_source(ParameterSource.ENVIRONMENT)
    assert "backends.interleaved_thinking_instructions_file" in env_params
