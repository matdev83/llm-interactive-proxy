"""Infrastructure layer for hybrid backend.

This module contains infrastructure components that handle external I/O
and backend interactions.
"""

from src.connectors.hybrid_backend.infrastructure.identity_resolver import (
    IdentityResolver,
)
from src.connectors.hybrid_backend.infrastructure.phase_executor import (
    PhaseExecutor,
)

__all__: list[str] = [
    "IdentityResolver",
    "PhaseExecutor",
]
