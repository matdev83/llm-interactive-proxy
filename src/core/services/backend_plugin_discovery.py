"""Discover optional backend plugins from Python entry points."""

from __future__ import annotations

import logging
import re
from importlib import metadata
from typing import cast

from src.core.common.backend_discovery_state import (
    PluginMetadataRecord,
    clear_plugin_metadata,
    clear_plugin_post_build_hooks,
    get_skipped_oauth_connectors,
    is_extracted_backend_name,
    is_running_in_multi_user_mode,
    normalize_backend_name,
    record_plugin_metadata,
    register_plugin_post_build_hook,
    replace_skipped_oauth_connectors,
)
from src.core.plugin_api import (
    BACKEND_PLUGIN_ENTRY_POINT_GROUP,
    BackendPluginDefinition,
    BackendPluginProvider,
)
from src.core.services.backend_registry import backend_registry

logger = logging.getLogger(__name__)

# Backward-compatible alias for tests/imports that already reference this symbol.
ENTRY_POINT_GROUP = BACKEND_PLUGIN_ENTRY_POINT_GROUP
_DEFAULT_CORE_VERSION = "0.1.0"

# Entry point names removed from optional oauth-connectors but still present in
# older installed distributions; skip without loading or logging a failure.
_RETIRED_BACKEND_PLUGIN_ENTRY_POINTS: frozenset[str] = frozenset({"anthropic-oauth"})


def discover_plugin_backends(entry_point_group: str = ENTRY_POINT_GROUP) -> list[str]:
    """Discover and register optional plugin backends.

    Fail-open semantics:
    - No entry points is a valid state.
    - Broken or incompatible plugins are skipped with actionable warnings.
    """
    clear_plugin_metadata()
    clear_plugin_post_build_hooks()
    current_core_version = _resolve_core_version()
    entry_points = _load_entry_points(entry_point_group)
    if not entry_points:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "No backend plugin entry points found for '%s'; running in core-only mode.",
                entry_point_group,
            )
        return []

    registered_backends: list[str] = []
    blocked_extracted_backends: set[str] = set()
    multi_user_mode = is_running_in_multi_user_mode()
    plugin_load_error_first_ep: dict[tuple[str, str], str] = {}
    seen_backend_names: set[str] = set()
    for entry_point in entry_points:
        if entry_point.name in _RETIRED_BACKEND_PLUGIN_ENTRY_POINTS:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Skipping retired backend plugin entry point %r.",
                    entry_point.name,
                )
            continue

        provider = _load_provider(entry_point, plugin_load_error_first_ep)
        if provider is None:
            continue

        definition = _load_definition(entry_point, provider)
        if definition is None:
            continue

        compatible, reason = _is_plugin_compatible(
            core_version=current_core_version,
            min_version=definition.compatibility.core_min_version,
            max_version=definition.compatibility.core_max_version,
        )
        if not compatible:
            logger.warning(
                "Skipping backend plugin '%s' from entry point '%s': %s.",
                definition.plugin_name,
                entry_point.name,
                reason,
            )
            continue

        backend_name = _deterministic_backend_name(entry_point, definition)
        normalized_backend_name = normalize_backend_name(backend_name)
        normalized_declared_name = normalize_backend_name(definition.backend_name)
        if multi_user_mode and (
            is_extracted_backend_name(normalized_backend_name)
            or is_extracted_backend_name(normalized_declared_name)
        ):
            blocked_extracted_backends.add(normalized_backend_name)
            logger.warning(
                "Skipping plugin backend '%s' from plugin '%s' in Multi User Mode. "
                "OAuth connectors are blocked in production deployments.",
                backend_name,
                definition.plugin_name,
            )
            continue

        if backend_name in seen_backend_names:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Skipping duplicate llm_proxy_backends entry point %r for backend %r "
                    "(already loaded from an earlier entry point).",
                    entry_point.name,
                    backend_name,
                )
            continue
        seen_backend_names.add(backend_name)

        if not backend_registry.register_backend(backend_name, definition.factory):
            continue

        record_plugin_metadata(
            PluginMetadataRecord(
                backend_name=backend_name,
                plugin_name=definition.plugin_name,
                core_min_version=definition.compatibility.core_min_version,
                core_max_version=definition.compatibility.core_max_version,
            )
        )
        if definition.post_build_hook is not None:
            register_plugin_post_build_hook(backend_name, definition.post_build_hook)
        registered_backends.append(backend_name)

    if blocked_extracted_backends:
        merged_skipped_connectors = set(get_skipped_oauth_connectors())
        merged_skipped_connectors.update(blocked_extracted_backends)
        replace_skipped_oauth_connectors(sorted(merged_skipped_connectors))

    return registered_backends


def _load_entry_points(entry_point_group: str) -> list[metadata.EntryPoint]:
    """Load entry points for a group with compatibility across Python versions."""
    try:
        # Python 3.10+ supports `group=` directly.
        return list(metadata.entry_points(group=entry_point_group))
    except TypeError:
        pass
    except Exception as exc:
        logger.warning(
            "Failed to enumerate backend plugin entry points for '%s': %s",
            entry_point_group,
            exc,
        )
        logger.debug(
            "Entry point enumeration failure for '%s'",
            entry_point_group,
            exc_info=True,
        )
        return []

    try:
        discovered = metadata.entry_points()
        if hasattr(discovered, "select"):
            selected = discovered.select(group=entry_point_group)
            return list(selected)
        legacy_mapping = cast(dict[str, list[metadata.EntryPoint]], discovered)
        return list(legacy_mapping.get(entry_point_group, []))
    except Exception as exc:
        logger.warning(
            "Failed to enumerate backend plugin entry points for '%s': %s",
            entry_point_group,
            exc,
        )
        logger.debug(
            "Entry point enumeration failure for '%s' (legacy path)",
            entry_point_group,
            exc_info=True,
        )
        return []


def _log_backend_plugin_load_failure(
    entry_point: metadata.EntryPoint,
    exc: BaseException,
    duplicate_load_errors: dict[tuple[str, str], str],
) -> None:
    """Log plugin entry-point load failure without spamming tracebacks at WARNING."""
    key = (type(exc).__name__, str(exc))
    first_entry_point = duplicate_load_errors.get(key)
    if first_entry_point is None:
        duplicate_load_errors[key] = entry_point.name
        logger.warning(
            "Failed to load backend plugin entry point '%s' (%s): %s: %s. "
            "If this backend is optional, install/update dependencies and restart.",
            entry_point.name,
            _entry_point_source(entry_point),
            type(exc).__name__,
            exc,
        )
        logger.debug(
            "Plugin entry point load traceback for '%s'",
            entry_point.name,
            exc_info=True,
        )
    else:
        logger.debug(
            "Skipping backend plugin entry point '%s' (%s): same load error as '%s' (%s: %s).",
            entry_point.name,
            _entry_point_source(entry_point),
            first_entry_point,
            type(exc).__name__,
            exc,
        )


def _load_provider(
    entry_point: metadata.EntryPoint,
    duplicate_load_errors: dict[tuple[str, str], str],
) -> BackendPluginProvider | None:
    """Load entry-point provider callable with fail-open warning behavior."""
    try:
        loaded = entry_point.load()
    except Exception as exc:
        _log_backend_plugin_load_failure(entry_point, exc, duplicate_load_errors)
        return None

    if not callable(loaded):
        logger.warning(
            "Skipping backend plugin entry point '%s': loaded object is not callable.",
            entry_point.name,
        )
        return None

    return cast(BackendPluginProvider, loaded)


def _load_definition(
    entry_point: metadata.EntryPoint, provider: BackendPluginProvider
) -> BackendPluginDefinition | None:
    """Load and validate plugin definition from provider."""
    try:
        definition = provider()
    except Exception as exc:
        logger.warning(
            "Skipping backend plugin entry point '%s': provider failed: %s.",
            entry_point.name,
            exc,
        )
        logger.debug(
            "Plugin provider failure for entry point '%s'",
            entry_point.name,
            exc_info=True,
        )
        return None

    if not isinstance(definition, BackendPluginDefinition):
        logger.warning(
            "Skipping backend plugin entry point '%s': provider must return "
            "BackendPluginDefinition (strict metadata contract).",
            entry_point.name,
        )
        return None

    if not definition.backend_name.strip():
        logger.warning(
            "Skipping backend plugin entry point '%s': backend_name is empty.",
            entry_point.name,
        )
        return None

    if not callable(definition.factory):
        logger.warning(
            "Skipping backend plugin entry point '%s': factory is not callable.",
            entry_point.name,
        )
        return None

    if not definition.plugin_name.strip():
        logger.warning(
            "Skipping backend plugin entry point '%s': plugin_name is required.",
            entry_point.name,
        )
        return None

    compatibility = definition.compatibility
    if (
        compatibility is None
        or not compatibility.core_min_version
        or not compatibility.core_min_version.strip()
    ):
        logger.warning(
            "Skipping backend plugin entry point '%s': compatibility.core_min_version "
            "is required (strict metadata contract).",
            entry_point.name,
        )
        return None

    if (
        compatibility.core_max_version is not None
        and not compatibility.core_max_version.strip()
    ):
        logger.warning(
            "Skipping backend plugin entry point '%s': compatibility.core_max_version "
            "must be a non-empty string when provided.",
            entry_point.name,
        )
        return None

    if definition.post_build_hook is not None and not callable(
        definition.post_build_hook
    ):
        logger.warning(
            "Skipping backend plugin entry point '%s': post_build_hook must be callable.",
            entry_point.name,
        )
        return None

    return definition


def _resolve_core_version() -> str:
    """Resolve running core version for compatibility checks."""
    try:
        return metadata.version("llm-interactive-proxy")
    except Exception:
        # Editable/in-repo workflows may not have distribution metadata yet.
        return _DEFAULT_CORE_VERSION


def _deterministic_backend_name(
    entry_point: metadata.EntryPoint, definition: BackendPluginDefinition
) -> str:
    """Use deterministic backend naming based on entry point declaration."""
    declared_name = definition.backend_name.strip()
    if declared_name == entry_point.name:
        return declared_name

    logger.warning(
        "Plugin '%s' entry point '%s' declares backend_name '%s'. "
        "Using entry point name for deterministic registration.",
        definition.plugin_name,
        entry_point.name,
        declared_name,
    )
    return entry_point.name


def _is_plugin_compatible(
    *, core_version: str, min_version: str, max_version: str | None
) -> tuple[bool, str]:
    """Validate plugin compatibility metadata against running core version."""
    core_tuple = _parse_version(core_version)
    min_tuple = _parse_version(min_version)
    if core_tuple is None or min_tuple is None:
        return (
            False,
            f"invalid version format (core={core_version!r}, min={min_version!r})",
        )

    if core_tuple < min_tuple:
        return (
            False,
            f"requires core>={min_version}, running core is {core_version}",
        )

    if max_version is None:
        return True, "compatible"

    max_tuple = _parse_version(max_version)
    if max_tuple is None:
        return False, f"invalid max version format: {max_version!r}"

    if core_tuple > max_tuple:
        return (
            False,
            f"supports core<={max_version}, running core is {core_version}",
        )

    return True, "compatible"


def _parse_version(value: str) -> tuple[int, int, int] | None:
    """Parse version string to comparable triplet.

    Parses leading numeric components and ignores suffixes (for example `0.1.0rc1`).
    """
    tokens = re.findall(r"\d+", value)
    if not tokens:
        return None

    numbers = [int(token) for token in tokens[:3]]
    while len(numbers) < 3:
        numbers.append(0)
    return numbers[0], numbers[1], numbers[2]


def _entry_point_source(entry_point: metadata.EntryPoint) -> str:
    """Return human-readable entry-point source for diagnostics."""
    dist = getattr(entry_point, "dist", None)
    dist_name = getattr(dist, "name", None)
    if isinstance(dist_name, str) and dist_name:
        return dist_name
    module = getattr(entry_point, "module", "")
    attr = getattr(entry_point, "attr", "")
    return f"{module}:{attr}"
