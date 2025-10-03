"""Backward-compatibility shim for backend factory service name.

This module re-exports BackendFactory from `backend_factory.py` to satisfy
imports that expect the _service suffix.
"""

from __future__ import annotations

import logging

from .backend_factory import BackendFactory

logging.debug(
    "Importing from 'src.core.services.backend_factory_service' is deprecated; "
    "use 'src.core.services.backend_factory' instead"
)

__all__ = ["BackendFactory"]
