"""Minimal pytz shim using zoneinfo for tests."""

from __future__ import annotations

from zoneinfo import ZoneInfo

__all__ = ["timezone"]


def timezone(name: str) -> ZoneInfo:  # pragma: no cover - thin wrapper
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")
