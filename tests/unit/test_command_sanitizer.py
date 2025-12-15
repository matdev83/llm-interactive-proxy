from __future__ import annotations

import pytest
from src.core.services.command_sanitizer import CommandSanitizer


class TestCommandSanitizer:
    @pytest.fixture
    def sanitizer(self) -> CommandSanitizer:
        return CommandSanitizer()

    @pytest.mark.parametrize(
        "content, expected",
        [
            ("Hello !/help()", "Hello"),
            ("!/help() world", "world"),
            ("Hi !/set(name=val) there", "Hi there"),
            ("No command here", "No command here"),
            ("", ""),
        ],
    )
    def test_sanitize(
        self, sanitizer: CommandSanitizer, content: str, expected: str
    ) -> None:
        assert sanitizer.sanitize(content) == expected
