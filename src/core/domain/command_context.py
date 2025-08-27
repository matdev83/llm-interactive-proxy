from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # Avoid runtime circular import
    from src.core.services.command_service import CommandRegistry  # pragma: no cover
else:  # Fallback type alias for runtime
    CommandRegistry = Any  # type: ignore


@dataclass(slots=True)
class CommandContext:
    """Typed context passed to commands during execution.

    Note: Fields mirror the ad-hoc attributes previously provided to commands
    to preserve compatibility during incremental migration.
    """

    command_registry: CommandRegistry
    backend_factory: Any | None = None
    backend_type: str | None = None
