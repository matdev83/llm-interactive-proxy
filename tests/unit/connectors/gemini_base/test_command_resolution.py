from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from src.connectors.gemini_base.command_resolution import (
    build_gemini_cli_command,
    resolve_gemini_cli_executable,
)


class TestGeminiCliCommandResolution:
    def test_resolve_default_gemini_prefers_windows_shims(self) -> None:
        def _fake_which(candidate: str) -> str | None:
            mapping = {
                "gemini": None,
                "gemini.cmd": r"C:\Users\mateusz\AppData\Roaming\npm\gemini.cmd",
                "gemini.exe": None,
                "gemini.bat": None,
            }
            return mapping.get(candidate)

        with (
            patch("src.connectors.gemini_base.command_resolution.os.name", "nt"),
            patch(
                "src.connectors.gemini_base.command_resolution.shutil.which",
                side_effect=_fake_which,
            ),
        ):
            resolved = resolve_gemini_cli_executable("gemini")

        assert resolved == r"C:\Users\mateusz\AppData\Roaming\npm\gemini.cmd"

    def test_build_command_wraps_windows_batch_shim(self) -> None:
        def _fake_which(candidate: str) -> str | None:
            mapping = {
                "gemini": None,
                "gemini.cmd": r"C:\Users\mateusz\AppData\Roaming\npm\gemini.cmd",
            }
            return mapping.get(candidate)

        with (
            patch("src.connectors.gemini_base.command_resolution.os.name", "nt"),
            patch(
                "src.connectors.gemini_base.command_resolution.shutil.which",
                side_effect=_fake_which,
            ),
        ):
            command = build_gemini_cli_command(["gemini", "--version"])

        expected_comspec = os.environ.get("COMSPEC", "cmd.exe")
        assert command == [
            expected_comspec,
            "/d",
            "/s",
            "/c",
            r"C:\Users\mateusz\AppData\Roaming\npm\gemini.cmd",
            "--version",
        ]

    def test_resolve_explicit_path_uses_direct_file(self, tmp_path: Path) -> None:
        executable = tmp_path / "gemini.cmd"
        executable.write_text("@echo off\r\n", encoding="utf-8")

        with (
            patch("src.connectors.gemini_base.command_resolution.os.name", "nt"),
            patch(
                "src.connectors.gemini_base.command_resolution.shutil.which",
                return_value=None,
            ),
        ):
            resolved = resolve_gemini_cli_executable(str(executable))

        assert resolved == str(executable.resolve())
