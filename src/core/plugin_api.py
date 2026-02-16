"""Stable plugin API contracts for external backend packages.

External backend packages should depend on this module only (not deep internals)
when declaring backends discoverable through ``llm_proxy_backends`` entry points.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

BACKEND_PLUGIN_ENTRY_POINT_GROUP = "llm_proxy_backends"

if TYPE_CHECKING:
    from src.core.interfaces.di_interface import IServiceProvider

BackendFactory = Callable[..., Any]
PluginPostBuildHook = Callable[["IServiceProvider"], None]


@dataclass(frozen=True)
class PluginCompatibility:
    """Core compatibility requirements declared by a plugin backend."""

    core_min_version: str
    core_max_version: str | None = None


@dataclass(frozen=True)
class BackendPluginDefinition:
    """Definition returned by plugin entry-point providers.

    ``post_build_hook`` is optional and executed only for successfully registered,
    compatible plugins after DI provider build.
    """

    backend_name: str
    factory: BackendFactory
    plugin_name: str
    compatibility: PluginCompatibility
    post_build_hook: PluginPostBuildHook | None = None


class BackendPluginProvider(Protocol):
    """Callable contract for entry-point providers."""

    def __call__(self) -> BackendPluginDefinition:
        """Return backend plugin definition for registration."""
        ...


__all__ = [
    "BACKEND_PLUGIN_ENTRY_POINT_GROUP",
    "BackendFactory",
    "PluginCompatibility",
    "PluginPostBuildHook",
    "BackendPluginDefinition",
    "BackendPluginProvider",
]
