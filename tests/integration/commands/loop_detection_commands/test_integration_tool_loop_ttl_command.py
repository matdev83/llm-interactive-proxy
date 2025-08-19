
import pytest
from unittest.mock import Mock
from src.core.domain.session import SessionState, LoopDetectionConfiguration
from src.command_parser import CommandParser
from src.command_config import CommandParserConfig

async def run_command(command_string: str) -> str:
    parser_config = Mock(spec=CommandParserConfig)
    parser_config.proxy_state = SessionState(loop_config=LoopDetectionConfiguration())
    parser_config.app = Mock()
    parser_config.preserve_unknown = True

    from src.core.domain.commands.loop_detection_commands.tool_loop_ttl_command import ToolLoopTTLCommand
    parser = CommandParser(parser_config, command_prefix="!/")
    parser.handlers = {"tool-loop-ttl": ToolLoopTTLCommand()} # Manually insert handler
    
    _, _ = await parser.process_messages([{"role": "user", "content": command_string}])
    
    if parser.command_results:
        return parser.command_results[-1].message
    return ""

@pytest.mark.asyncio
async def test_ttl_success_snapshot(snapshot):
    """Snapshot test for a successful tool-loop-ttl command."""
    command_string = "!/tool-loop-ttl(ttl_seconds=120)"
    output_message = await run_command(command_string)
    assert output_message == snapshot

@pytest.mark.asyncio
async def test_ttl_failure_snapshot(snapshot):
    """Snapshot test for a failing tool-loop-ttl command."""
    command_string = "!/tool-loop-ttl(ttl_seconds=invalid)"
    output_message = await run_command(command_string)
    assert output_message == snapshot
