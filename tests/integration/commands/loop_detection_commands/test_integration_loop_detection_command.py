import pytest
from src.core.domain.chat import ChatMessage
from src.core.domain.session import LoopDetectionConfiguration, SessionState
from src.core.services.command_processor import (
    CommandProcessor as CoreCommandProcessor,
)
from src.core.services.command_service import CommandRegistry, CommandService


async def run_command(command_string: str) -> str:
    # Build a minimal DI-driven command processor with the loop-detection command
    from src.core.domain.commands.loop_detection_commands.loop_detection_command import (
        LoopDetectionCommand,
    )

    registry = CommandRegistry()
    registry.register(LoopDetectionCommand())

    class _SessionSvc:
        async def get_session(self, session_id: str):
            # Provide a full Session with loop detection config
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
    # Extract the last command result message (via CommandResultWrapper.message)
    if result.command_results:
        last = result.command_results[-1]
        # Support both wrapper and direct CommandResult
        return getattr(
            last, "message", getattr(getattr(last, "result", None), "message", "")
        )
    return ""


@pytest.mark.asyncio
async def test_loop_detection_enable_snapshot(snapshot):
    """Snapshot test for enabling loop detection."""
    command_string = "!/loop-detection(enabled=true)"
    output_message = await run_command(command_string)
    snapshot.assert_match(output_message, "loop_detection_enable_output")


@pytest.mark.asyncio
async def test_loop_detection_disable_snapshot(snapshot):
    """Snapshot test for disabling loop detection."""
    command_string = "!/loop-detection(enabled=false)"
    output_message = await run_command(command_string)
    snapshot.assert_match(output_message, "loop_detection_disable_output")


@pytest.mark.asyncio
async def test_loop_detection_default_snapshot(snapshot):
    """Snapshot test for default loop detection command."""
    command_string = "!/loop-detection()"
    output_message = await run_command(command_string)
    snapshot.assert_match(output_message, "loop_detection_default_output")
