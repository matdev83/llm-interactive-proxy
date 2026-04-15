"""Shared workspace path rules for ACP backends (session / request hints)."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

ACP_BACKEND_TYPES: frozenset[str] = frozenset(
    {
        "gemini-cli-acp",
        "cursor-cli-acp",
    }
)

ACP_MISSING_PROJECT_WORKSPACE_CODE = "acp_missing_project_workspace"

ACP_WORKSPACE_OPTION_KEYS: tuple[str, ...] = (
    "project_dir",
    "workspace_path",
    "cwd",
    "project",
)

ACP_MISSING_PROJECT_WORKSPACE_CODE = "acp_missing_project_workspace"


def extract_workspace_override_from_mapping(m: Mapping[str, Any]) -> str | None:
    """Return the first non-empty workspace hint string from a single mapping."""

    for key in ACP_WORKSPACE_OPTION_KEYS:
        value = m.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def first_workspace_hint_str(*candidates: Mapping[str, Any] | None) -> str | None:
    """First non-empty workspace hint across mappings (extra_body, options, …)."""

    for mapping in candidates:
        if mapping is None:
            continue
        found = extract_workspace_override_from_mapping(mapping)
        if found is not None:
            return found
    return None


def is_usable_workspace_directory(path: Path) -> bool:
    """True when ``path`` is an existing readable directory."""

    return path.exists() and path.is_dir() and os.access(path, os.R_OK)


def first_usable_workspace_dir(
    *candidates: Mapping[str, Any] | None,
    is_usable: Callable[[Path], bool] | None = None,
) -> Path | None:
    """Resolve the first usable directory from workspace hints across mappings."""

    checker = is_usable or is_usable_workspace_directory
    for mapping in candidates:
        if mapping is None:
            continue
        raw = extract_workspace_override_from_mapping(mapping)
        if raw is None:
            continue
        try:
            candidate = Path(raw).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if checker(candidate):
            return candidate
    return None
