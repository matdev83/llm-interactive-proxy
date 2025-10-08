"""Compatibility layer exposing the legacy :mod:`src.core.cli_v2` API.

Historically the proxy shipped a ``cli_v2`` module while the staged CLI
implementation was being validated.  The canonical implementation now lives in
:mod:`src.core.cli`, but some tooling and documentation in the wider ecosystem
may still reference the old module path.  To keep those integrations working
we expose thin wrappers that delegate to the modern implementation.

The wrappers are intentionally lightweight so that importers continue to obtain
fully featured behaviour without depending on implementation details of
:mod:`src.core.cli`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from src.core import cli as _cli_module

AppConfig = _cli_module.AppConfig

__all__ = [
    "AppConfig",
    "apply_cli_args",
    "is_port_in_use",
    "main",
    "parse_cli_args",
]


def parse_cli_args(argv: list[str] | None = None) -> Any:
    """Parse CLI arguments using the canonical implementation."""

    return _cli_module.parse_cli_args(argv)


def apply_cli_args(args: Any) -> AppConfig:
    """Apply parsed CLI arguments to an :class:`AppConfig` instance."""

    return _cli_module.apply_cli_args(args)


def is_port_in_use(host: str, port: int) -> bool:
    """Return ``True`` when the supplied host/port is already bound."""

    return _cli_module.is_port_in_use(host, port)


def main(
    argv: list[str] | None = None,
    build_app_fn: Callable[[AppConfig], FastAPI] | None = None,
) -> None:
    """Entry-point retained for backwards compatibility with ``cli_v2``."""

    _cli_module.main(argv=argv, build_app_fn=build_app_fn)
