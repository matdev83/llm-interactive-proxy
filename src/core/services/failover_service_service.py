"""Shim exposing FailoverService under _service name."""

from __future__ import annotations

import warnings

from .failover_service import FailoverService

warnings.warn(
    "Importing from 'src.core.services.failover_service_service' is deprecated; use 'src.core.services.failover_service' instead",
    DeprecationWarning,
)

__all__ = ["FailoverService"]


