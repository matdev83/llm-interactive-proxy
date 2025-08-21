from unittest.mock import Mock

import pytest

pytestmark = pytest.mark.skip(
    reason="Snapshot fixture not available - requires significant test infrastructure setup"
)
from src.command_config import CommandParserConfig
from src.command_parser import CommandParser
from src.core.domain.session import LoopDetectionConfiguration, SessionState


async def run_command(command_string: str) -> str:
    parser_config = Mock(spec=CommandParserConfig)
    parser_config.proxy_state = SessionState(loop_config=LoopDetectionConfiguration())
    parser_config.app = Mock()
    parser_config.preserve_unknown = True

    from src.core.domain.commands.loop_detection_commands.loop_detection_command import (
        LoopDetectionCommand,
    )

    parser = CommandParser(parser_config, command_prefix="!/")
    parser.handlers = {
        "loop-detection": LoopDetectionCommand()
    }  # Manually insert handler

    _, _ = await parser.process_messages([{"role": "user", "content": command_string}])

    if parser.command_results:
        return parser.command_results[-1].message
    return ""


@pytest.mark.asyncio
async def test_loop_detection_enable_snapshot(snapshot):
    """Snapshot test for enabling loop detection."""
    command_string = "!/loop-detection(enabled=true)"
    output_message = await run_command(command_string)
    assert output_message == snapshot


@pytest.mark.asyncio
async def test_loop_detection_disable_snapshot(snapshot):
    """Snapshot test for disabling loop detection."""
    command_string = "!/loop-detection(enabled=false)"
    output_message = await run_command(command_string)
    assert output_message == snapshot


@pytest.mark.asyncio
async def test_loop_detection_default_snapshot(snapshot):
    """Snapshot test for default loop detection command."""
    command_string = "!/loop-detection()"
    output_message = await run_command(command_string)
    assert output_message == snapshot
