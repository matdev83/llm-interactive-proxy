"""B2BUA session identifier generation helpers."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Final
from uuid import UUID, uuid4

_A_SESSION_PREFIX: Final[str] = "llm-b2bua-"
_B_SESSION_PREFIX: Final[str] = "llm-b2bua-b-"
_A_SESSION_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^llm-b2bua-(?P<a_uuid>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)
_HEADER_SAFE_IDENTIFIER_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9-]+$")


class B2BUASessionIdFactory:
    """Generate A-leg and B-leg session identifiers for B2BUA mode."""

    def __init__(self, uuid_factory: Callable[[], UUID] | None = None) -> None:
        self._uuid_factory = uuid_factory if uuid_factory is not None else uuid4

    def generate_a_session_id(self) -> str:
        """Create a new A-leg identifier in canonical format."""
        return f"{_A_SESSION_PREFIX}{self._uuid_factory()}"

    def generate_b_session_id(self, a_session_id: str, seq: int) -> str:
        """Create a B-leg identifier bound to A-leg UUID and sequence number."""
        if seq < 1:
            raise ValueError("seq must be >= 1")

        canonical_a_uuid = self.extract_a_uuid(a_session_id)
        return f"{_B_SESSION_PREFIX}{canonical_a_uuid}-{seq}"

    @staticmethod
    def extract_a_uuid(a_session_id: str) -> str:
        """Extract and canonicalize the UUID component from an A-leg identifier."""
        if not isinstance(a_session_id, str):
            raise ValueError("Invalid a_session_id format")

        candidate = a_session_id.strip()
        match = _A_SESSION_PATTERN.fullmatch(candidate)
        if match is None:
            raise ValueError("Invalid a_session_id format")

        try:
            return str(UUID(match.group("a_uuid")))
        except ValueError as exc:
            raise ValueError("Invalid a_session_id format") from exc

    @staticmethod
    def is_header_safe(identifier: str) -> bool:
        """Return True when identifier is safe to place in HTTP headers."""
        return _HEADER_SAFE_IDENTIFIER_PATTERN.fullmatch(identifier) is not None
