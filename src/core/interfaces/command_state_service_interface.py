from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.commands.session_state_adapter import SessionStateAdapter
    from src.core.domain.session import Session


class ICommandStateService(ABC):
    """Interface that encapsulates secure access to session state."""

    @abstractmethod
    async def get_session(self, session_id: str) -> Session | None:
        """Return the session for the provided id, if it exists."""

    @abstractmethod
    async def update_session(self, session: Session) -> None:
        """Persist the provided session."""

    @abstractmethod
    def build_session_adapter(self, session: Session) -> SessionStateAdapter:
        """Return a secure adapter exposing the session state."""
