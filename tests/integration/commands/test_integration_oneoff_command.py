
from unittest.mock import Mock

import pytest

# Removed skip marker - now have snapshot fixture available
from src.command_config import CommandParserConfig
from src.command_parser import CommandParser
from src.core.domain.session import BackendConfiguration, SessionState
from src.core.domain.chat import ChatMessage


async def run_command(command_string: str) -> str:
    parser_config = Mock(spec=CommandParserConfig)
    parser_config.proxy_state = SessionState(backend_config=BackendConfiguration())
    parser_config.app = Mock()
    parser_config.preserve_unknown = True

    from src.core.domain.commands.oneoff_command import OneoffCommand
    parser = CommandParser(parser_config, command_prefix="!/")
    parser.handlers = {"oneoff": OneoffCommand()} # Manually insert handler
    
    _, _ = await parser.process_messages([ChatMessage(role="user", content=command_string)])
    
    if parser.command_results:
        return parser.command_results[-1].message
    return ""

@pytest.mark.asyncio
async def test_oneoff_success_snapshot(snapshot):
    """Snapshot test for a successful oneoff command."""
    command_string = "!/oneoff(gemini/gemini-pro)"
    output_message = await run_command(command_string)
    assert output_message == snapshot(output_message)

@pytest.mark.asyncio
async def test_oneoff_failure_snapshot(snapshot):
    """Snapshot test for a failing oneoff command."""
    command_string = "!/oneoff(invalid-format)"
    output_message = await run_command(command_string)
    assert output_message == snapshot(output_message)
