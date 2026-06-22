"""Cross-platform Gemini CLI command resolution helpers."""

from __future__ import annotations

import os
import shutil
from collections.abc import Sequence
from pathlib import Path, PureWindowsPath

_WINDOWS_BATCH_SUFFIXES = {".bat", ".cmd"}
_WINDOWS_GEMINI_CANDIDATES = ("gemini.cmd", "gemini.exe", "gemini.bat", "gemini")
_HOST_PATH_CLASS = type(Path())


def _is_path_like(candidate: str) -> bool:
    windows_path = PureWindowsPath(candidate)
    return bool(windows_path.anchor) or any(
        separator and separator in candidate for separator in (os.sep, os.altsep)
    )


def _resolve_specific_executable(candidate: str) -> str | None:
    normalized = candidate.strip()
    if not normalized:
        return None

    if _is_path_like(normalized):
        path = _HOST_PATH_CLASS(normalized).expanduser()
        if path.is_file():
            return str(path.resolve())
        return None

    resolved = shutil.which(normalized)
    if resolved:
        return resolved
    return None


def resolve_gemini_cli_executable(
    preferred_executable: str | None = None,
) -> str | None:
    """Resolve the Gemini CLI executable for the current platform."""

    candidate = (preferred_executable or "").strip()
    if candidate:
        resolved = _resolve_specific_executable(candidate)
        if resolved:
            return resolved

        # Preserve explicit overrides unless the caller is using the default bare
        # "gemini" command, which should also fall back to common Windows shims.
        if PureWindowsPath(candidate).name.lower() == "gemini" and not _is_path_like(
            candidate
        ):
            for fallback in _WINDOWS_GEMINI_CANDIDATES:
                resolved = _resolve_specific_executable(fallback)
                if resolved:
                    return resolved
        return None

    candidates = _WINDOWS_GEMINI_CANDIDATES if os.name == "nt" else ("gemini",)
    for fallback in candidates:
        resolved = _resolve_specific_executable(fallback)
        if resolved:
            return resolved
    return None


def build_gemini_cli_command(command: Sequence[str]) -> list[str]:
    """Build an executable Gemini CLI command suitable for subprocess APIs."""

    if not command:
        raise ValueError("Gemini CLI command cannot be empty")

    executable = resolve_gemini_cli_executable(command[0])
    if executable is None:
        raise FileNotFoundError(f"gemini CLI executable not found: {command[0]}")

    resolved_command = [executable, *command[1:]]
    if (
        os.name == "nt"
        and PureWindowsPath(executable).suffix.lower() in _WINDOWS_BATCH_SUFFIXES
    ):
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        return [comspec, "/d", "/s", "/c", *resolved_command]
    return resolved_command


__all__ = [
    "build_gemini_cli_command",
    "resolve_gemini_cli_executable",
]
