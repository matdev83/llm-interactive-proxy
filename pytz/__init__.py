"""Minimal pytz stub for test execution."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class _ZoneInfo:
    name: str

    def localize(self, dt: datetime, is_dst: bool | None = None) -> datetime:  # pragma: no cover - trivial
        del is_dst
        return dt


def timezone(name: str) -> _ZoneInfo:
    return _ZoneInfo(name)


UTC = timezone("UTC")
