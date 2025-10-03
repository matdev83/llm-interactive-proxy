"""Minimal stub for the ``pytz`` package used in tests."""

from __future__ import annotations

from datetime import timezone as _timezone

__all__ = ["UTC", "timezone"]


class _Utc:
    def localize(self, dt):  # type: ignore[no-untyped-def]
        return dt.replace(tzinfo=_timezone.utc)


UTC = _Utc()


def timezone(name: str):  # type: ignore[no-untyped-def]
    if name.upper() == "UTC":
        return UTC
    raise ValueError(f"Unsupported timezone stub: {name}")
