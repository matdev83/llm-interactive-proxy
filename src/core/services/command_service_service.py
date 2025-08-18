"""Shim exposing CommandService and CommandRegistry under _service name."""

from __future__ import annotations

import warnings

from .command_service import CommandService, CommandRegistry

warnings.warn(
    "Importing from 'src.core.services.command_service_service' is deprecated; use 'src.core.services.command_service' instead",
    DeprecationWarning,
)

__all__ = ["CommandService", "CommandRegistry"]


