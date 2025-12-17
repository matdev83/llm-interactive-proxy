from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.core.config.env.from_env_part1 import build_config_part1
from src.core.config.env.from_env_part2 import apply_config_part2
from src.core.config.env.from_env_part3 import apply_config_part3
from src.core.config.parameter_resolution import ParameterResolution


def build_app_config_dict_from_env(
    *,
    environ: Mapping[str, str],
    resolution: ParameterResolution | None = None,
) -> dict[str, Any]:
    config = build_config_part1(environ, resolution)
    apply_config_part2(config, environ, resolution)
    apply_config_part3(config, environ, resolution)
    return config
