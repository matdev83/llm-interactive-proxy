"""B-leg allocation service for per-attempt backend identity."""

from __future__ import annotations

from dataclasses import dataclass

from src.core.interfaces.b2bua_mapping_store_interface import IB2buaMappingStore
from src.core.services.b2bua_session_id_factory import B2BUASessionIdFactory


@dataclass(frozen=True)
class BlegAllocation:
    """Result of a B-leg allocation for one backend attempt."""

    b_session_id: str
    seq: int


class B2buaBlegAllocator:
    """Allocate attempt-scoped B-leg identifiers and record attempt metadata."""

    def __init__(
        self,
        *,
        mapping_store: IB2buaMappingStore,
        session_id_factory: B2BUASessionIdFactory,
    ) -> None:
        self._mapping_store = mapping_store
        self._session_id_factory = session_id_factory

    async def allocate(
        self,
        *,
        a_session_id: str,
        backend_type: str | None,
        effective_model: str | None,
        reason: str | None,
    ) -> BlegAllocation:
        """Allocate B-leg identity and persist attempt diagnostics."""
        seq = await self._mapping_store.allocate_next_b_seq(a_session_id)
        b_session_id = self._session_id_factory.generate_b_session_id(a_session_id, seq)
        await self._mapping_store.record_attempt(
            a_session_id=a_session_id,
            b_session_id=b_session_id,
            seq=seq,
            backend_type=backend_type,
            effective_model=effective_model,
            reason=reason,
        )
        return BlegAllocation(b_session_id=b_session_id, seq=seq)
