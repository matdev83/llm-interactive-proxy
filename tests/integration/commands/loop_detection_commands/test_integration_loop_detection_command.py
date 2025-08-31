import pytest
from src.core.commands.parser import CommandParser
from src.core.commands.service import NewCommandService
from src.core.domain.chat import ChatMessage
from src.core.domain.session import LoopDetectionConfiguration, SessionState
from src.core.services.command_processor import (
    CommandProcessor as CoreCommandProcessor,
)


async def run_command(command_string: str) -> str:
    # Build a minimal DI-driven command processor with the loop-detection command
    from src.core.interfaces.session_service_interface import ISessionService

    class _SessionSvc(ISessionService):
        async def get_session(self, session_id: str):
            # Provide a full Session with loop detection config
            from src.core.domain.session import Session

            return Session(
                session_id=session_id,
                state=SessionState(loop_config=LoopDetectionConfiguration()),
            )

        async def get_session_async(self, session_id: str):
            return await self.get_session(session_id)

        async def create_session(self, session_id: str):
            from src.core.domain.session import Session

            return Session(
                session_id=session_id,
                state=SessionState(loop_config=LoopDetectionConfiguration()),
            )

        async def get_or_create_session(self, session_id: str | None = None):
            from src.core.domain.session import Session

            return Session(
                session_id=session_id or "default",
                state=SessionState(loop_config=LoopDetectionConfiguration()),
            )

        async def update_session(self, session):
            return None

        async def update_session_backend_config(
            self, session_id: str, backend_type: str, model: str
        ) -> None:
            return None

        async def delete_session(self, session_id: str) -> bool:
            return True

        async def get_all_sessions(self) -> list:
            return []

    processor = CoreCommandProcessor(
        NewCommandService(session_service=_SessionSvc(), command_parser=CommandParser())
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
    command_string = "!/tool-loop-detection(enabled=true)"
    output_message = await run_command(command_string)
    snapshot.assert_match(output_message, "loop_detection_enable_output")


@pytest.mark.asyncio
async def test_loop_detection_disable_snapshot(snapshot):
    """Snapshot test for disabling loop detection."""
    command_string = "!/tool-loop-detection(enabled=false)"
    output_message = await run_command(command_string)
    snapshot.assert_match(output_message, "loop_detection_disable_output")


@pytest.mark.asyncio
async def test_loop_detection_default_snapshot(snapshot):
    """Snapshot test for default loop detection command."""
    command_string = "!/tool-loop-detection()"
    output_message = await run_command(command_string)
    snapshot.assert_match(output_message, "loop_detection_default_output")
