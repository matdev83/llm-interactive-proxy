"""Configuration for edit precision model-specific temperature settings."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

try:  # pragma: no cover - optional dependency
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    yaml = None  # type: ignore

from pydantic import Field

from src.core.interfaces.model_bases import DomainModel

logger = logging.getLogger(__name__)

# Module-level cache to avoid reloading on every request
_cached_config: EditPrecisionTemperaturesConfig | None = None


class ModelTemperaturePattern(DomainModel):
    """Temperature override pattern for a model family."""

    pattern: str = Field(
        description="Substring to match in model name (case-insensitive)"
    )
    temperature: float = Field(
        ge=0.0, le=2.0, description="Temperature to apply for matching models"
    )
    comment: str | None = Field(
        default=None, description="Optional comment explaining this pattern"
    )


class EditPrecisionTemperaturesConfig(DomainModel):
    """Configuration for model-specific temperature overrides during edit precision mode."""

    default_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="Default temperature when no pattern matches",
    )
    model_patterns: list[ModelTemperaturePattern] = Field(
        default_factory=list, description="Model-specific temperature patterns"
    )

    def get_temperature_for_model(self, model_name: str) -> float:
        """
        Get the appropriate temperature for a given model name.

        Args:
            model_name: The model name to match against patterns

        Returns:
            Temperature value to use for this model
        """
        if not model_name:
            return self.default_temperature

        model_lower = model_name.lower()
        for pattern in self.model_patterns:
            if pattern.pattern.lower() in model_lower:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        f"Matched model '{model_name}' to pattern '{pattern.pattern}' -> temperature={pattern.temperature}"
                    )
                return pattern.temperature

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"No pattern matched for model '{model_name}', using default temperature={self.default_temperature}"
            )
        return self.default_temperature


def load_edit_precision_temperatures_config(
    config_path: str | Path | None = None,
    force_reload: bool = False,
) -> EditPrecisionTemperaturesConfig:
    """
    Load edit precision temperatures configuration from YAML file.

    Uses module-level caching to avoid reloading on every request.

    Args:
        config_path: Path to configuration file. If None, uses default location.
        force_reload: If True, bypass cache and reload from file.

    Returns:
        EditPrecisionTemperaturesConfig instance
    """
    global _cached_config

    # Track if we're using default path for caching
    using_default_path = config_path is None

    # Return cached config if available and not forcing reload
    if not force_reload and _cached_config is not None and using_default_path:
        return _cached_config

    if config_path is None:
        # Default to config/edit_precision_model_temperatures.yaml in project root
        # __file__ is src/core/config/edit_precision_temperatures.py
        # parent is src/core/config, parent.parent is src/core, parent.parent.parent is src
        # We need to go up 3 levels (to src), then one more to get to project root
        config_path = (
            Path(__file__).parent.parent.parent.parent
            / "config"
            / "edit_precision_model_temperatures.yaml"
        )
    else:
        config_path = Path(config_path)

    if yaml is None:
        logger.warning(
            "PyYAML is not installed; edit precision temperature overrides will use defaults"
        )
        config = EditPrecisionTemperaturesConfig()
        if using_default_path:
            _cached_config = config
        return config

    if not config_path.exists():
        logger.warning(
            f"Edit precision temperatures config not found at {config_path}, using defaults"
        )
        config = EditPrecisionTemperaturesConfig()
        # Cache the default config
        if using_default_path:
            _cached_config = config
        return config

    try:
        with open(config_path, encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f)

        if not data:
            logger.warning(
                "Edit precision temperatures config is empty, using defaults"
            )
            config = EditPrecisionTemperaturesConfig()
        else:
            config = EditPrecisionTemperaturesConfig(**data)
            logger.info(
                f"Loaded edit precision temperatures config with {len(config.model_patterns)} patterns"
            )

        # Cache the loaded config if using default path
        if using_default_path:
            _cached_config = config

        return config

    except Exception as e:
        logger.error(
            f"Failed to load edit precision temperatures config from {config_path}: {e}",
            exc_info=True,
        )
        config = EditPrecisionTemperaturesConfig()
        # Cache even on error to avoid repeated failed attempts
        if using_default_path:
            _cached_config = config
        return config
