"""Compatibility shims for legacy model module imports."""

from __future__ import annotations

import sys
from types import ModuleType

from src.core.config.app_config import BackendConfig

__all__ = ["BackendConfig"]


def _install_backend_config_module() -> None:
    """Expose ``BackendConfig`` under the legacy module path."""

    module_name = f"{__name__}.backend_config"
    if module_name in sys.modules:
        return

    shim = ModuleType(module_name)
    shim.BackendConfig = BackendConfig  # type: ignore
    sys.modules[module_name] = shim


_install_backend_config_module()
