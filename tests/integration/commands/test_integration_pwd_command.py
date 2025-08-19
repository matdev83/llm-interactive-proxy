
import pytest
from unittest.mock import Mock
from src.core.domain.session import SessionState
from src.command_parser import CommandParser
from src.command_config import CommandParserConfig

async def run_command(initial_state: SessionState) -> str:
    parser_config = Mock(spec=CommandParserConfig)
    parser_config.proxy_state = initial_state
    parser_config.app = Mock()
    parser_config.preserve_unknown = True

    from src.core.domain.commands.pwd_command import PwdCommand
    parser = CommandParser(parser_config, command_prefix="!/")
    parser.handlers = {"pwd": PwdCommand()} # Manually insert handler
    
    _, _ = await parser.process_messages([{"role": "user", "content": "!/pwd"}])
    
    if parser.command_results:
        return parser.command_results[-1].message
    return ""

@pytest.mark.asyncio
async def test_pwd_with_dir_set_snapshot(snapshot):
    """Snapshot test for the pwd command when a directory is set."""
    initial_state = SessionState(project_dir="/path/to/a/cool/project")
    output_message = await run_command(initial_state)
    assert output_message == snapshot

@pytest.mark.asyncio
async def test_pwd_with_dir_not_set_snapshot(snapshot):
    """Snapshot test for the pwd command when no directory is set."""
    initial_state = SessionState(project_dir=None)
    output_message = await run_command(initial_state)
    assert output_message == snapshot
