from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.core.config.dict_utils import get_by_path, set_by_path
from src.core.config.env.from_env import build_app_config_dict_from_env
from src.core.config.models.app_config_model import AppConfigModel
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource


class EnvironmentConfigSource:
    """Load configuration overrides from environment variables."""

    def load(
        self,
        environ: Mapping[str, str],
        *,
        resolution: ParameterResolution,
    ) -> dict[str, Any]:
        import logging
        logger = logging.getLogger(__name__)
        full_env_config = build_app_config_dict_from_env(
            environ=environ, resolution=resolution
        )
        if "backends" in full_env_config and "kimi-code" in full_env_config["backends"]:
             logger.warning("DIAG: full_env_config has kimi-code")
        
        env_model = AppConfigModel.model_validate(full_env_config)
        env_dump = env_model.model_dump()

        env_only: dict[str, Any] = {}
        for name in resolution.latest_by_source(ParameterSource.ENVIRONMENT):
            value = get_by_path(env_dump, name)
            set_by_path(env_only, name, value)
        return env_only
