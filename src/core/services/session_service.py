"""Shim exposing SessionService under _service name.

This file acts as a thin shim re-exporting the concrete implementation from
`src.core.services.session_service_impl` to keep imports stable during the
refactor.
"""

from __future__ import annotations

import logging

from .session_service_impl import SessionService

logging.debug(
    "Importing from 'src.core.services.session_service' shim is deprecated; "
    "use 'src.core.services.session_service_impl' instead"
)

__all__ = ["SessionService"]
