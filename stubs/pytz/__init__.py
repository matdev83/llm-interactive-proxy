"""Minimal stub for the ``pytz`` package used in tests."""

from __future__ import annotations

from datetime import timezone as dt_timezone

__all__ = ["timezone", "UTC"]


class _Utc:
    def localize(self, dt):  # type: ignore[no-untyped-def]
        return dt.replace(tzinfo=dt_timezone.utc)


UTC = _Utc()


def timezone(name: str):  # type: ignore[no-untyped-def]
    if name.upper() == "UTC":
        return UTC
    raise ValueError(f"Unsupported timezone stub: {name}")
