"""Shim exposing BackendConfigService under _service name."""

from __future__ import annotations

import warnings

from .backend_config_service import BackendConfigService

warnings.warn(
    "Importing from 'src.core.services.backend_config_service_service' is deprecated; use 'src.core.services.backend_config_service' instead",
    DeprecationWarning,
)

__all__ = ["BackendConfigService"]


