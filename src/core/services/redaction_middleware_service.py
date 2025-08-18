"""Shim exposing RedactionMiddleware under _service name."""

from __future__ import annotations

import warnings

from .redaction_middleware import RedactionMiddleware, APIKeyRedactor, ProxyCommandFilter

warnings.warn(
    "Importing from 'src.core.services.redaction_middleware_service' is deprecated; use 'src.core.services.redaction_middleware' instead",
    DeprecationWarning,
)

__all__ = ["RedactionMiddleware", "APIKeyRedactor", "ProxyCommandFilter"]


