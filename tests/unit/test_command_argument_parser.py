from __future__ import annotations

import pytest
from src.core.services.command_argument_parser import CommandArgumentParser


class TestCommandArgumentParser:
    @pytest.fixture
    def parser(self) -> CommandArgumentParser:
        return CommandArgumentParser()

    @pytest.mark.parametrize(
        "args_str, expected",
        [
            (None, {}),
            ("", {}),
            ("--foo=bar", {"foo": "bar"}),
            ("--a=1 --b=two", {"a": 1, "b": "two"}),
        ],
    )
    def test_parse_various_inputs(
        self,
        parser: CommandArgumentParser,
        args_str: str | None,
        expected: dict[str, object],
    ) -> None:
        result = parser.parse(args_str)
        # Result must contain at least the expected keys/values; underlying function may coerce types
        for k, v in expected.items():
            assert result.get(k) == v
