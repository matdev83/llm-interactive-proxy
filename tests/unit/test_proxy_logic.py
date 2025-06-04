import pytest
from src.proxy_logic import (
    parse_arguments,
    # _process_text_for_commands, # No longer used here
    # process_commands_in_messages, # No longer used here
    ProxyState # Keep ProxyState if TestParseArguments might need it, or remove if not
)
# from src.models import ChatMessage, MessageContentPart, MessageContentPartText, MessageContentPartImage, ImageURL # No longer used here

class TestParseArguments:
    def test_parse_valid_arguments(self):
        args_str = "model=gpt-4, temperature=0.7, max_tokens=100"
        expected = {"model": "gpt-4", "temperature": "0.7", "max_tokens": "100"}
        assert parse_arguments(args_str) == expected

    def test_parse_empty_arguments(self):
        assert parse_arguments("") == {}
        assert parse_arguments("   ") == {}

    def test_parse_arguments_with_slashes_in_model_name(self):
        args_str = "model=organization/model-name, temperature=0.5"
        expected = {"model": "organization/model-name", "temperature": "0.5"}
        assert parse_arguments(args_str) == expected

    def test_parse_arguments_single_argument(self):
        args_str = "model=gpt-3.5-turbo"
        expected = {"model": "gpt-3.5-turbo"}
        assert parse_arguments(args_str) == expected

    def test_parse_arguments_with_spaces(self):
        args_str = " model = gpt-4 , temperature = 0.8 "
        expected = {"model": "gpt-4", "temperature": "0.8"}
        assert parse_arguments(args_str) == expected

    def test_parse_flag_argument(self):
        # E.g. !/unset(model) -> model is a key, not key=value
        args_str = "model"
        expected = {"model": True}
        assert parse_arguments(args_str) == expected

    def test_parse_mixed_arguments(self):
        args_str = "model=claude/opus, debug_mode"
        expected = {"model": "claude/opus", "debug_mode": True}
        assert parse_arguments(args_str) == expected

# Removed TestProcessTextForCommands and TestProcessCommandsInMessages
# as they are now in dedicated files:
# tests/unit/proxy_logic_tests/test_process_text_for_commands.py
# tests/unit/proxy_logic_tests/test_process_commands_in_messages.py
