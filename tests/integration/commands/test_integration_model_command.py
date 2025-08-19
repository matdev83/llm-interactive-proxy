
from unittest.mock import Mock

import pytest
from src.command_config import CommandParserConfig
from src.command_parser import CommandParser
from src.core.domain.session import BackendConfiguration, SessionState


async def run_command(command_string: str) -> str:
    parser_config = Mock(spec=CommandParserConfig)
    parser_config.proxy_state = SessionState(backend_config=BackendConfiguration())
    parser_config.app = Mock()
    parser_config.preserve_unknown = True

    from src.core.domain.commands.model_command import ModelCommand
    parser = CommandParser(parser_config, command_prefix="!/")
    parser.handlers = {"model": ModelCommand()} # Manually insert handler
    
    _, _ = await parser.process_messages([{"role": "user", "content": command_string}])
    
    if parser.command_results:
        return parser.command_results[-1].message
    return ""

@pytest.mark.asyncio
async def test_set_model_snapshot(snapshot):
    """Snapshot test for setting a model."""
    command_string = "!/model(name=gpt-4-turbo)"
    output_message = await run_command(command_string)
    assert output_message == snapshot

@pytest.mark.asyncio
async def test_set_model_with_backend_snapshot(snapshot):
    """Snapshot test for setting a model with a backend."""
    command_string = "!/model(name=openrouter:claude-3-opus)"
    output_message = await run_command(command_string)
    assert output_message == snapshot

@pytest.mark.asyncio
async def test_unset_model_snapshot(snapshot):
    """Snapshot test for unsetting a model."""
    command_string = "!/model(name=)" # Unset by providing an empty name
    output_message = await run_command(command_string)
    assert output_message == snapshot
