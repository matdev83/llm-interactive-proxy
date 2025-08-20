
from unittest.mock import Mock

import pytest

pytestmark = pytest.mark.skip(reason="Snapshot fixture not available - requires significant test infrastructure setup")
from src.command_config import CommandParserConfig
from src.command_parser import CommandParser
from src.core.domain.session import LoopDetectionConfiguration, SessionState


async def run_command(command_string: str) -> str:
    parser_config = Mock(spec=CommandParserConfig)
    parser_config.proxy_state = SessionState(loop_config=LoopDetectionConfiguration())
    parser_config.app = Mock()
    parser_config.preserve_unknown = True

    from src.core.domain.commands.loop_detection_commands.tool_loop_max_repeats_command import (
        ToolLoopMaxRepeatsCommand,
    )
    parser = CommandParser(parser_config, command_prefix="!/")
    parser.handlers = {"tool-loop-max-repeats": ToolLoopMaxRepeatsCommand()} # Manually insert handler
    
    _, _ = await parser.process_messages([{"role": "user", "content": command_string}])
    
    if parser.command_results:
        return parser.command_results[-1].message
    return ""

@pytest.mark.asyncio
async def test_max_repeats_success_snapshot(snapshot):
    """Snapshot test for a successful tool-loop-max-repeats command."""
    command_string = "!/tool-loop-max-repeats(max_repeats=5)"
    output_message = await run_command(command_string)
    assert output_message == snapshot

@pytest.mark.asyncio
async def test_max_repeats_failure_snapshot(snapshot):
    """Snapshot test for a failing tool-loop-max-repeats command."""
    command_string = "!/tool-loop-max-repeats(max_repeats=abc)"
    output_message = await run_command(command_string)
    assert output_message == snapshot
