from __future__ import annotations

import argparse
from pathlib import Path

import pytest
from src.core.cli import build_cli_parser

SNAPSHOT_PATH = Path(__file__).resolve().parents[2] / "data" / "cli_flag_snapshot.txt"


def _collect_cli_flags(parser: argparse.ArgumentParser) -> list[str]:
    """Return a sorted list of all CLI option strings defined on the parser."""
    flags: set[str] = set()
    for action in parser._actions:
        for option in action.option_strings:
            if option.startswith("-"):
                flags.add(option)
    return sorted(flags)


def test_cli_flag_snapshot() -> None:
    """Ensure all previously recorded CLI flags remain available."""

    parser = build_cli_parser()
    current_flags = _collect_cli_flags(parser)

    snapshot_path = SNAPSHOT_PATH
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    if not snapshot_path.exists():
        snapshot_path.write_text("\n".join(current_flags) + "\n", encoding="utf-8")
        pytest.fail(
            "CLI flag snapshot created at data/cli_flag_snapshot.txt. "
            "Review the file and commit it to the repository."
        )

    stored_flags = [
        line.strip()
        for line in snapshot_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    stored_set = set(stored_flags)
    current_set = set(current_flags)

    missing_flags = sorted(stored_set - current_set)
    if missing_flags:
        pytest.fail(
            "CLI flag regression detected. Flags stored in snapshot but absent "
            "from parser: " + ", ".join(missing_flags)
        )

    new_flags = sorted(current_set - stored_set)
    if new_flags:
        snapshot_path.write_text("\n".join(current_flags) + "\n", encoding="utf-8")
        pytest.fail(
            "CLI flag snapshot updated automatically. Newly detected flags: "
            + ", ".join(new_flags)
        )
