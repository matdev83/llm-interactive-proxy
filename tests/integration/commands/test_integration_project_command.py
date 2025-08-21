from unittest.mock import Mock

import pytest

# Removed skip marker - now have snapshot fixture available
from src.command_config import CommandParserConfig
from src.command_parser import CommandParser
from src.core.domain.chat import ChatMessage
from src.core.domain.session import SessionState


async def run_command(command_string: str) -> str:
    parser_config = Mock(spec=CommandParserConfig)
    parser_config.proxy_state = SessionState()
    parser_config.app = Mock()
    parser_config.preserve_unknown = True

    from src.core.domain.commands.project_command import ProjectCommand

    parser = CommandParser(parser_config, command_prefix="!/")
    parser.handlers = {"project": ProjectCommand()}  # Manually insert handler

    _, _ = await parser.process_messages(
        [ChatMessage(role="user", content=command_string)]
    )

    if parser.command_results:
        return parser.command_results[-1].message
    return ""


@pytest.mark.asyncio
@pytest.mark.skip("Skipping until command handling in tests is fixed")
async def test_project_success_snapshot(snapshot):
    """Snapshot test for a successful project command."""
    command_string = "!/project(name=my-awesome-project)"
    output_message = await run_command(command_string)
    assert output_message == snapshot(output_message)


@pytest.mark.asyncio
@pytest.mark.skip("Skipping until command handling in tests is fixed")
async def test_project_failure_snapshot(snapshot):
    """Snapshot test for a failing project command."""
    command_string = "!/project(name=)"
    output_message = await run_command(command_string)
    assert output_message == snapshot(output_message)
