from __future__ import annotations

import sys


def test_parse_cli_args_tolerates_unknown_sys_argv(monkeypatch) -> None:
    from src.core.config.cli_args import parse_cli_args

    monkeypatch.setattr(
        sys,
        "argv",
        ["prog", "--host", "0.0.0.0", "--unknown-flag", "value"],
    )

    parsed = parse_cli_args()

    assert parsed["host"] == "0.0.0.0"
