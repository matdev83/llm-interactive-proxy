"""Helpers for managing optional test dependencies.

The cloud execution environment used by Codex runs a lean Python image that
omits a number of optional packages such as ``pytest-asyncio`` and
``pytest-httpx``.  Several test modules rely on these packages.  When they are
missing the standard imports raise ``ModuleNotFoundError`` during test
collection which prevents *all* tests from running.

To keep the suite runnable in minimal environments we provide small helper
functions that attempt to import the optional dependency and skip the
requesting test module if it is unavailable.  Each helper returns the imported
module so test files can continue to use their normal APIs when the dependency
is present.
"""

from __future__ import annotations

from importlib import import_module
from types import ModuleType

import pytest


def _require_module(module_name: str, package_name: str) -> ModuleType:
    """Import *module_name* or skip the calling test module.

    Parameters
    ----------
    module_name:
        The fully-qualified module name to import.
    package_name:
        The corresponding package name used for the user-facing skip message.
    """

    try:
        return import_module(module_name)
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised in CI
        pytest.skip(
            (
                f"Optional test dependency '{package_name}' is not installed. "
                "Install it via the '[dev]' extras to run these tests."
            ),
            allow_module_level=True,
        )
        raise RuntimeError from exc


def require_pytest_asyncio() -> ModuleType:
    """Return the ``pytest_asyncio`` module or skip if absent."""

    return _require_module("pytest_asyncio", "pytest-asyncio")


def require_pytest_httpx() -> ModuleType:
    """Return the ``pytest_httpx`` module or skip if absent."""

    return _require_module("pytest_httpx", "pytest-httpx")


def require_respx() -> ModuleType:
    """Return the ``respx`` module or skip if absent."""

    return _require_module("respx", "respx")


def require_hypothesis() -> ModuleType:
    """Return the ``hypothesis`` module or skip if absent."""

    return _require_module("hypothesis", "hypothesis")


def require_pytest_mock() -> ModuleType:
    """Return the ``pytest_mock`` module or skip if absent."""

    return _require_module("pytest_mock", "pytest-mock")

