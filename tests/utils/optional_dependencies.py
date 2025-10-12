"""Utilities for handling optional test dependencies.

These helpers allow tests to gracefully skip when optional third-party
packages are not installed in the execution environment. This is
particularly useful for CI environments that only install the core
project dependencies but omit heavyweight testing extras.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Optional

import pytest


def require_module(module_name: str, *, reason: Optional[str] = None) -> ModuleType:
    """Import ``module_name`` or skip the current test module.

    The function attempts to import the requested module. If the module is
    unavailable, ``pytest.skip`` is invoked with ``allow_module_level=True`` so
    that the entire test module is skipped during collection instead of raising
    an import error.

    Args:
        module_name: The dotted path of the module to import.
        reason: Optional human-readable explanation for the skip message.

    Returns:
        The imported module when available.
    """
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised in CI
        skip_reason = reason or f"Optional dependency '{module_name}' is not installed"
        pytest.skip(skip_reason, allow_module_level=True)
        raise AssertionError("pytest.skip should halt execution") from exc
