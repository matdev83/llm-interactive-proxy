"""Contract tests for command normalization prior to dangerous-command scanning."""

import pytest
from src.core.domain.configuration.dangerous_command_config import is_dangerous_command
from src.core.domain.security.command_normalization import (
    normalize_command_for_security_scan,
)


def test_normalize_strips_embedded_ansi_csi_sgr_sequences() -> None:
    raw = "echo \x1b[31mred\x1b[0m and \x1b[1;33myellow\x1b[m done"
    normalized = normalize_command_for_security_scan(raw)
    assert "\x1b" not in normalized
    assert normalized.split() == ["echo", "red", "and", "yellow", "done"]


def test_normalize_removes_nul_bytes() -> None:
    raw = "git\x00 reset --hard"
    normalized = normalize_command_for_security_scan(raw)
    assert "\x00" not in normalized
    assert normalized == "git reset --hard"


def test_normalize_applies_unicode_nfkc_fullwidth_latin() -> None:
    # U+FF47 FULLWIDTH LATIN SMALL LETTER G, U+FF49 I, U+FF54 T
    fullwidth_git_only = "\uff47\uff49\uff54"
    assert normalize_command_for_security_scan(fullwidth_git_only) == "git"


@pytest.mark.parametrize(
    "masked_reset",
    [
        "\uff47\uff49\uff54 reset --hard",
        "\x1b[31m\uff47\uff49\uff54\x1b[0m reset --hard",
        "\uff47\uff49\uff54\x00 reset --hard",
    ],
)
def test_normalize_unmasks_git_reset_hard_for_detection(masked_reset: str) -> None:
    normalized = normalize_command_for_security_scan(masked_reset)
    assert "git reset --hard" in normalized
    assert is_dangerous_command(normalized) is True
