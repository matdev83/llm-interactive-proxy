"""Backward-compatibility shim for `src.core.services.backend_registry_service`.

This module re-exports the existing `backend_registry` implementation from
`src.core.services.backend_registry` to avoid breaking imports during the
refactor. Update callers to import from `backend_registry` directly.
"""

from __future__ import annotations

import logging

from .backend_registry import BackendRegistry, backend_registry

logging.debug(
    "Importing from 'src.core.services.backend_registry_service' is deprecated; "
    "use 'src.core.services.backend_registry' instead"
)

__all__ = ["BackendRegistry", "backend_registry"]
