
from unittest.mock import Mock

import pytest
from src.command_config import CommandParserConfig
from src.command_parser import CommandParser
from src.core.domain.session import ReasoningConfiguration, SessionState


async def run_command(command_string: str) -> str:
    parser_config = Mock(spec=CommandParserConfig)
    parser_config.proxy_state = SessionState(reasoning_config=ReasoningConfiguration())
    parser_config.app = Mock()
    parser_config.preserve_unknown = True

    from src.core.domain.commands.temperature_command import TemperatureCommand
    parser = CommandParser(parser_config, command_prefix="!/")
    parser.handlers = {"temperature": TemperatureCommand()} # Manually insert handler
    
    _, _ = await parser.process_messages([{"role": "user", "content": command_string}])
    
    if parser.command_results:
        return parser.command_results[-1].message
    return ""

@pytest.mark.asyncio
async def test_temperature_success_snapshot(snapshot):
    """Snapshot test for a successful temperature command."""
    command_string = "!/temperature(value=0.9)"
    output_message = await run_command(command_string)
    assert output_message == snapshot

@pytest.mark.asyncio
async def test_temperature_failure_snapshot(snapshot):
    """Snapshot test for a failing temperature command."""
    command_string = "!/temperature(value=invalid)"
    output_message = await run_command(command_string)
    assert output_message == snapshot
