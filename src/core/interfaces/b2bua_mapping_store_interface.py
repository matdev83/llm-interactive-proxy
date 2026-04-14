"""Interfaces for B2BUA continuity mapping stores."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class B2buaContinuityResolution:
    """Result of continuity mapping resolution."""

    a_session_id: str
    reused_existing: bool
    had_store_error: bool = False


@dataclass(frozen=True)
class B2buaAttemptRecord:
    """Diagnostic metadata recorded for one backend attempt leg."""

    b_session_id: str
    a_session_id: str
    seq: int
    backend_type: str | None = None
    effective_model: str | None = None
    reason: str | None = None


class IB2buaMappingStore(ABC):
    """Resolve or create A-leg continuity mapping entries."""

    @abstractmethod
    async def resolve_or_create_a_session_id(
        self,
        *,
        auth_scope_id: str,
        client_session_id: str,
        create_a_session_id: Callable[[], str],
    ) -> B2buaContinuityResolution:
        """Resolve active mapping or create a new A-leg session id."""

    @abstractmethod
    async def allocate_next_b_seq(self, a_session_id: str) -> int:
        """Atomically allocate the next B-leg sequence for an active A-leg."""

    @abstractmethod
    async def record_attempt(
        self,
        *,
        a_session_id: str,
        b_session_id: str,
        seq: int,
        backend_type: str | None,
        effective_model: str | None,
        reason: str | None,
    ) -> None:
        """Record attempt metadata and retain it for diagnostics."""

    @abstractmethod
    async def get_attempt_records(self, a_session_id: str) -> list[B2buaAttemptRecord]:
        """Return recorded backend attempts for a single A-leg session."""

    @abstractmethod
    async def try_resolve_echoed_a_session_id(
        self,
        *,
        a_session_id: str,
        requesting_auth_scope_id: str | None,
    ) -> B2buaContinuityResolution | None:
        """Resolve an active A-leg when the client echoes a prior ``llm-b2bua-...`` id.

        Returns ``None`` when unknown, expired, or when auth scope does not allow reuse.
        """
