"""Shim exposing SyncSessionManager under _service name."""

from __future__ import annotations

import warnings

from .sync_session_manager import SyncSessionManager

warnings.warn(
    "Importing from 'src.core.services.sync_session_manager_service' is deprecated; use 'src.core.services.sync_session_manager' instead",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["SyncSessionManager"]
