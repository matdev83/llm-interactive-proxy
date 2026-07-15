"""Connector-safe model catalog discovery contracts."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class BackendModelEnumeration:
    """Complete model-discovery result for one configured backend instance."""

    instance_name: str
    connector: str
    models: tuple[str, ...]
    source: str
    status: str
    instance_pinned: bool
    error_code: str | None = None

    @classmethod
    def available(
        cls,
        *,
        instance_name: str,
        connector: str,
        models: Iterable[str],
        source: str,
        instance_pinned: bool,
    ) -> BackendModelEnumeration:
        return cls(
            instance_name=instance_name,
            connector=connector,
            models=tuple(dict.fromkeys(str(model) for model in models if str(model))),
            source=source,
            status="available",
            instance_pinned=instance_pinned,
        )

    @classmethod
    def unavailable(
        cls,
        *,
        instance_name: str,
        connector: str,
        source: str,
        error_code: str,
        instance_pinned: bool,
    ) -> BackendModelEnumeration:
        return cls(
            instance_name=instance_name,
            connector=connector,
            models=(),
            source=source,
            status="unavailable",
            error_code=error_code,
            instance_pinned=instance_pinned,
        )


__all__ = ["BackendModelEnumeration"]
