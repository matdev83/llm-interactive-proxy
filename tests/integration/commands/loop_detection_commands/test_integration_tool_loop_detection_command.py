import pytest
from src.core.commands.parser import CommandParser
from src.core.commands.service import NewCommandService

# Unskip: snapshot fixture is available in test suite
from src.core.domain.chat import ChatMessage
from src.core.domain.session import LoopDetectionConfiguration, SessionState
from src.core.services.command_processor import (
    CommandProcessor as CoreCommandProcessor,
)


async def run_command(command_string: str) -> str:

    class _SessionSvc:
        async def get_session(self, session_id: str):
            from src.core.domain.session import Session

            return Session(
                session_id=session_id,
                state=SessionState(loop_config=LoopDetectionConfiguration()),
            )

        async def update_session(self, session):
            return None

    processor = CoreCommandProcessor(
        NewCommandService(session_service=_SessionSvc(), command_parser=CommandParser())
    )

    result = await processor.process_messages(
        [ChatMessage(role="user", content=command_string)],
        session_id="snapshot-session",
    )
    if result.command_results:
        last = result.command_results[-1]
        return getattr(
            last, "message", getattr(getattr(last, "result", None), "message", "")
        )
    return ""


@pytest.mark.asyncio
async def test_tool_loop_detection_enable_snapshot(snapshot):
    """Snapshot test for enabling tool loop detection."""
    command_string = "!/tool-loop-detection(enabled=true)"
    output_message = await run_command(command_string)
    snapshot.assert_match(output_message, "tool_loop_detection_enable_output")


@pytest.mark.asyncio
async def test_tool_loop_detection_disable_snapshot(snapshot):
    """Snapshot test for disabling tool loop detection."""
    command_string = "!/tool-loop-detection(enabled=false)"
    output_message = await run_command(command_string)
    snapshot.assert_match(output_message, "tool_loop_detection_disable_output")


@pytest.mark.asyncio
async def test_tool_loop_detection_default_snapshot(snapshot):
    """Snapshot test for default tool loop detection command."""
    command_string = "!/tool-loop-detection()"
    output_message = await run_command(command_string)
    snapshot.assert_match(output_message, "tool_loop_detection_default_output")
