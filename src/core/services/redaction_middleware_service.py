"""Shim exposing RedactionMiddleware under _service name."""

from __future__ import annotations

import warnings

from .redaction_middleware import (
    APIKeyRedactor,
    ProxyCommandFilter,
    RedactionMiddleware,
)

warnings.warn(
    "Importing from 'src.core.services.redaction_middleware_service' is deprecated; use 'src.core.services.redaction_middleware' instead",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["APIKeyRedactor", "ProxyCommandFilter", "RedactionMiddleware"]
