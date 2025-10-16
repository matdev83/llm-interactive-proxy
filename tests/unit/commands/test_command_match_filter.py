from __future__ import annotations

import pytest
from src.core.commands.parser import CommandParser, ParsedCommand
from src.core.commands.pipeline.match_filter import CommandMatchFilter


class TestCommandMatchFilter:
    @pytest.fixture
    def match_filter(self) -> CommandMatchFilter:
        return CommandMatchFilter()

    @pytest.fixture
    def command_parser(self) -> CommandParser:
        return CommandParser(command_prefix="!/")

    def test_filters_command_present_at_tail(
        self,
        match_filter: CommandMatchFilter,
        command_parser: CommandParser,
    ) -> None:
        tail_text = "something !/set(temperature=0.1)"
        parsed: list[ParsedCommand] = command_parser.parse(tail_text)
        assert parsed

        result = match_filter.filter_tail_commands(
            parsed, tail_text=tail_text, message_index=3
        )

        assert len(result) == 1
        assert result[0].command == parsed[-1]
        assert result[0].message_index == 3

    def test_rejects_command_not_at_tail(
        self,
        match_filter: CommandMatchFilter,
        command_parser: CommandParser,
    ) -> None:
        tail_text = "!/set(temperature=0.1) extra"
        parsed: list[ParsedCommand] = command_parser.parse(tail_text)
        assert parsed

        result = match_filter.filter_tail_commands(
            parsed, tail_text=tail_text, message_index=0
        )

        assert result == []

    def test_handles_multiple_candidates_with_only_tail_match_kept(
        self,
        match_filter: CommandMatchFilter,
        command_parser: CommandParser,
    ) -> None:
        tail_text = "intro !/hello body !/unset(model)   "
        parsed: list[ParsedCommand] = command_parser.parse(tail_text)
        assert len(parsed) == 2

        result = match_filter.filter_tail_commands(
            parsed, tail_text=tail_text, message_index=1
        )

        assert len(result) == 1
        assert result[0].command == parsed[-1]

    def test_keeps_trailing_command_with_whitespace(
        self,
        match_filter: CommandMatchFilter,
        command_parser: CommandParser,
    ) -> None:
        tail_text = "!/set(model=openrouter:gpt-4)   \n"
        parsed: list[ParsedCommand] = command_parser.parse(tail_text)
        assert len(parsed) == 1

        result = match_filter.filter_tail_commands(
            parsed, tail_text=tail_text, message_index=0
        )

        assert len(result) == 1
        assert result[0].command == parsed[0]
