"""Shared state for backend discovery diagnostics and plugin metadata."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.plugin_api import PluginPostBuildHook


@dataclass(frozen=True)
class PluginMetadataRecord:
    """Compatibility metadata persisted for a discovered plugin backend."""

    backend_name: str
    plugin_name: str
    core_min_version: str
    core_max_version: str | None


_oauth_install_command = "pip install llm-interactive-proxy[oauth]"
_optional_oauth_package_name = "llm-interactive-proxy-oauth-connectors"
_extracted_backends_env = "LLM_PROXY_EXTRACTED_BACKENDS"
_backend_plugin_entry_point_group = "llm_proxy_backends"

_lock = Lock()
_is_multi_user_mode = False
_skipped_oauth_connectors: set[str] = set()
_plugin_metadata: dict[str, PluginMetadataRecord] = {}
_plugin_post_build_hooks: dict[str, PluginPostBuildHook] = {}


def set_discovery_mode(*, is_multi_user_mode: bool) -> None:
    """Record the access mode used during backend discovery."""
    global _is_multi_user_mode
    with _lock:
        _is_multi_user_mode = is_multi_user_mode


def normalize_backend_name(raw_name: str) -> str:
    """Normalize backend/instance names into canonical backend key form."""
    normalized = raw_name.strip().lower().replace("_", "-")
    if "." in normalized:
        normalized = normalized.split(".", 1)[0]
    return normalized


def _looks_like_oauth_backend(raw_name: str) -> bool:
    normalized = normalize_backend_name(raw_name)
    return normalized.endswith("-oauth") or "-oauth-" in normalized


def filter_oauth_style_backend_names(backend_names: Iterable[str]) -> list[str]:
    """Return backend names that follow the OAuth connector naming convention.

    Uses structural pattern only (no hardcoded names). Convention: *-oauth or *-oauth-*
    """
    return sorted(name for name in backend_names if _looks_like_oauth_backend(name))


def _load_entry_points(group: str) -> list[Any]:
    """Load plugin entry points through canonical discovery helper.

    Keep metadata enumeration implementation centralized in
    src.core.services.backend_plugin_discovery for DRY compliance.
    """
    try:
        from src.core.services.backend_plugin_discovery import (
            _load_entry_points as _load,
        )

        return list(_load(group))
    except Exception:
        return []


def _load_extracted_from_environment() -> set[str]:
    raw = os.getenv(_extracted_backends_env, "")
    names = {
        normalize_backend_name(name)
        for name in raw.split(",")
        if normalize_backend_name(name)
    }
    return {name for name in names if _looks_like_oauth_backend(name)}


def _resolve_extracted_backend_names() -> frozenset[str]:
    names: set[str] = set()
    names.update(_load_extracted_from_environment())

    for entry_point in _load_entry_points(_backend_plugin_entry_point_group):
        dist = getattr(entry_point, "dist", None)
        dist_name = getattr(dist, "name", None)
        entry_point_name = getattr(entry_point, "name", "")
        if not isinstance(entry_point_name, str) or not entry_point_name:
            continue
        normalized_name = normalize_backend_name(entry_point_name)

        # All backends shipped in the dedicated optional package are "extracted",
        # including names that do not follow the *-oauth suffix convention.
        if dist_name == _optional_oauth_package_name:
            names.add(normalized_name)
            continue

        if not _looks_like_oauth_backend(normalized_name):
            continue

        # If distribution metadata is missing, still accept oauth-like backend names.
        if dist_name and dist_name != _optional_oauth_package_name:
            continue
        names.add(normalized_name)

    return frozenset(sorted(names))


def get_extracted_backend_names() -> list[str]:
    """Return extracted oauth backend names from plugins/env discovery."""
    return sorted(_resolve_extracted_backend_names())


def get_extracted_connector_module_names() -> list[str]:
    """Return connector module names for extracted backends (underscore style)."""
    return sorted(name.replace("-", "_") for name in _resolve_extracted_backend_names())


def is_extracted_backend_name(raw_name: str) -> bool:
    """Check whether a backend/instance belongs to extracted optional set."""
    normalized = normalize_backend_name(raw_name)
    return (
        normalized in _resolve_extracted_backend_names()
        or _looks_like_oauth_backend(normalized)
    )


def get_oauth_install_command() -> str:
    """Return install command for optional OAuth connector package."""
    return _oauth_install_command


def get_optional_oauth_package_name() -> str:
    """Return distribution name for optional OAuth connector package."""
    return _optional_oauth_package_name


def replace_skipped_oauth_connectors(skipped_connectors: list[str]) -> None:
    """Replace OAuth connectors skipped during the latest discovery run."""
    with _lock:
        _skipped_oauth_connectors.clear()
        _skipped_oauth_connectors.update(skipped_connectors)


def get_skipped_oauth_connectors() -> list[str]:
    """Get OAuth connectors skipped during latest discovery run."""
    with _lock:
        return sorted(_skipped_oauth_connectors)


def is_running_in_multi_user_mode() -> bool:
    """Return whether the last discovery run used Multi User Mode."""
    with _lock:
        return _is_multi_user_mode


def record_plugin_metadata(record: PluginMetadataRecord) -> None:
    """Persist plugin metadata by backend name for diagnostics/safety checks."""
    with _lock:
        _plugin_metadata[record.backend_name] = record


def get_plugin_metadata(backend_name: str) -> PluginMetadataRecord | None:
    """Fetch persisted metadata for a discovered plugin backend."""
    with _lock:
        return _plugin_metadata.get(backend_name)


def clear_plugin_metadata() -> None:
    """Clear plugin metadata records before a fresh discovery cycle."""
    with _lock:
        _plugin_metadata.clear()


def register_plugin_post_build_hook(
    backend_name: str, hook: PluginPostBuildHook
) -> None:
    """Persist optional plugin post-build hook by backend name."""
    with _lock:
        _plugin_post_build_hooks[backend_name] = hook


def get_plugin_post_build_hooks() -> list[tuple[str, PluginPostBuildHook]]:
    """Return deterministic list of registered plugin post-build hooks."""
    with _lock:
        return sorted(_plugin_post_build_hooks.items(), key=lambda item: item[0])


def clear_plugin_post_build_hooks() -> None:
    """Clear plugin post-build hooks before a fresh discovery cycle."""
    with _lock:
        _plugin_post_build_hooks.clear()
