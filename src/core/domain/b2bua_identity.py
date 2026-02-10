"""Proxy-internal B2BUA identity carrier."""

from __future__ import annotations

from dataclasses import dataclass, replace

from src.core.interfaces.model_bases import InternalDTO


@dataclass(frozen=True)
class B2buaIdentity(InternalDTO):
    """Identity carrier for A-leg/B-leg session separation.

    This model is proxy-internal and must not be projected to connector-facing
    boundaries verbatim. Connector projections may only expose redacted,
    connector-safe metadata.
    """

    a_session_id: str
    b_session_id: str | None = None
    client_session_id: str | None = None
    auth_scope_id: str | None = None
    b_seq: int | None = None

    def __post_init__(self) -> None:
        if not self.a_session_id or not self.a_session_id.strip():
            raise ValueError("a_session_id must be a non-empty string")
        if self.b_session_id is not None and not self.b_session_id.strip():
            raise ValueError("b_session_id cannot be empty when provided")
        if self.b_seq is not None and self.b_seq < 1:
            raise ValueError("b_seq must be a positive integer when provided")

    def with_attempt(self, *, b_session_id: str, b_seq: int | None) -> B2buaIdentity:
        """Create a copy with attempt-scoped B-leg identity."""
        return replace(self, b_session_id=b_session_id, b_seq=b_seq)
