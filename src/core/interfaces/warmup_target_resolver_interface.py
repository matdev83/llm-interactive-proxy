"""Interface for backend-specific warm-up target expansion."""

from __future__ import annotations

from abc import ABC, abstractmethod


class IWarmupTargetResolver(ABC):
    """Resolve backend-specific warm-up targets.

    A warm-up target is a backend-internal identity such as an account id.
    Backends that don't support fan-out should return an empty list.
    """

    @abstractmethod
    async def resolve_target_accounts(self, backend_type: str) -> list[str]:
        """Return account identifiers to fan-out warm-up requests for."""
