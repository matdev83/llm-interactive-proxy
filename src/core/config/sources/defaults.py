from __future__ import annotations

from typing import Any

from src.core.config.models.app_config_model import AppConfigModel


class DefaultsConfigSource:
    """Provide configuration defaults from the domain model."""

    def load(self) -> dict[str, Any]:
        return AppConfigModel().model_dump()
