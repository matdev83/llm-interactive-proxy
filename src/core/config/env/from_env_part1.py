from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.core.config.env.from_env_part1a import build_config_part1a
from src.core.config.env.from_env_part1b import apply_config_part1b
from src.core.config.parameter_resolution import ParameterResolution


def build_config_part1(
    env: Mapping[str, str],
    resolution: ParameterResolution | None,
) -> dict[str, Any]:
    config, planning_overrides = build_config_part1a(env, resolution)
    apply_config_part1b(config, env, resolution, planning_overrides)
    return config
