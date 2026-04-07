"""Utility helpers for environment-driven feature flags."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping

_TRUE_VALUES = {"1", "true", "yes", "on"}


def get_env_flag(name: str, default: bool) -> bool:
    """Return a boolean flag sourced from the environment."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in _TRUE_VALUES


def get_env_value_with_windows_persistent_fallback(
    name: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[str | None, str]:
    """Return env value, preferring Windows persistent env when process snapshot is stale.

    Windows processes inherit an environment snapshot from their parent. If the user
    updates a persistent User/Machine environment variable and restarts the proxy via a
    launcher that still holds the old snapshot, ``os.environ`` can be stale even though
    the currently configured Windows environment contains the newer value.

    Returns a tuple of ``(value, source)`` where source is one of:
    ``process``, ``windows-user``, ``windows-machine``, or ``missing``.
    """

    env_map = os.environ if environ is None else environ
    process_value = env_map.get(name)

    if sys.platform != "win32":
        return process_value, "process" if process_value else "missing"

    persistent_value, persistent_source = _get_windows_persistent_env_value(name)
    if persistent_value and persistent_value != process_value:
        return persistent_value, persistent_source
    if process_value:
        return process_value, "process"
    if persistent_value:
        return persistent_value, persistent_source
    return None, "missing"


def _get_windows_persistent_env_value(name: str) -> tuple[str | None, str]:
    try:
        import winreg
    except ImportError:
        return None, "missing"

    locations = (
        (winreg.HKEY_CURRENT_USER, r"Environment", "windows-user"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
            "windows-machine",
        ),
    )

    for hive, subkey, source in locations:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _ = winreg.QueryValueEx(key, name)
        except OSError:
            continue
        if isinstance(value, str) and value:
            return value, source

    return None, "missing"
