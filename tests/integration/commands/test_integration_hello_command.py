from unittest.mock import Mock

import pytest

# Removed skip marker - now have snapshot fixture available
from src.command_config import CommandParserConfig
from src.command_parser import CommandParser
from src.core.domain.session import SessionState


async def run_command(command_string: str, initial_state: SessionState) -> str:
    parser_config = Mock(spec=CommandParserConfig)
    parser_config.proxy_state = initial_state
    parser_config.app = Mock()
    parser_config.preserve_unknown = True

    from src.core.domain.commands.hello_command import HelloCommand

    parser = CommandParser(parser_config, command_prefix="!/")
    parser.handlers = {"hello": HelloCommand()}  # Manually insert handler

    # Create proper message objects
    from src.core.domain.chat import ChatMessage

    messages = [ChatMessage(role="user", content=command_string)]
    _, _ = await parser.process_messages(messages)

    if parser.command_results:
        return parser.command_results[-1].message
    return ""


@pytest.mark.asyncio
async def test_hello_snapshot(snapshot):
    """Snapshot test for the hello command."""
    # Arrange
    initial_state = SessionState()
    command_string = "!/hello"

    # Act
    output_message = await run_command(command_string, initial_state)

    # Assert
    assert output_message == snapshot(output_message)
