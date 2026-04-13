"""Table-driven checks for the canonical combined dangerous-command matcher."""

import pytest
from src.core.domain.configuration.dangerous_command_config import is_dangerous_command


@pytest.mark.parametrize(
    "command, expected",
    [
        ("git reset --hard", True),
        ("GIT RESET --HARD", True),
        ("git status", False),
        ("echo hello", False),
        ("rm -rf /tmp/foo", True),
        ("git push --force origin main", True),
    ],
)
def test_is_dangerous_command_matches_combined_pattern(
    command: str, expected: bool
) -> None:
    assert is_dangerous_command(command) is expected
