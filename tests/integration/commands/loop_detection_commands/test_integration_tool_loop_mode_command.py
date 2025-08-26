import pytest

# Unskip: snapshot fixture is available in test suite
from src.core.domain.chat import ChatMessage
from src.core.domain.session import LoopDetectionConfiguration, SessionState
from src.core.services.command_processor import (
    CommandProcessor as CoreCommandProcessor,
)
from src.core.services.command_service import CommandRegistry, CommandService


async def run_command(command_string: str) -> str:
    from src.core.domain.commands.loop_detection_commands.tool_loop_mode_command import (
        ToolLoopModeCommand,
    )

    registry = CommandRegistry()
    registry.register(ToolLoopModeCommand())

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
        CommandService(registry, session_service=_SessionSvc())
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
async def test_tool_loop_mode_success_snapshot(snapshot):
    """Snapshot test for a successful tool-loop-mode command."""
    command_string = "!/tool-loop-mode(mode=relaxed)"
    output_message = await run_command(command_string)
    snapshot.assert_match(output_message, "tool_loop_mode_success_output")


@pytest.mark.asyncio
async def test_tool_loop_mode_failure_snapshot(snapshot):
    """Snapshot test for a failing tool-loop-mode command."""
    command_string = "!/tool-loop-mode(mode=invalid_mode)"
    output_message = await run_command(command_string)
    snapshot.assert_match(output_message, "tool_loop_mode_failure_output")
