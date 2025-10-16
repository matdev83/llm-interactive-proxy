from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.domain.session import Session


class ICommandPolicyService(ABC):
    """Interface describing policy decisions for interactive commands."""

    @abstractmethod
    def is_static_route_enforced(self) -> bool:
        """Return True when backend/model changes must be blocked."""

    @abstractmethod
    def are_interactive_commands_disabled(self, session: Session | None = None) -> bool:
        """Return True when interactive commands should be ignored."""

    @abstractmethod
    def should_apply_strict_detection(self) -> bool:
        """Return True when detection must only consider trailing commands."""

    @abstractmethod
    def resolve_command_prefix(
        self, session: Session | None, fallback_prefix: str
    ) -> str:
        """Return the effective command prefix for the provided session."""
