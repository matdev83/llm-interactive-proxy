import pytest
from src.core.commands.parser import CommandParser
from src.core.commands.service import NewCommandService

# Unskip: snapshot fixture is available in test suite
from src.core.domain.chat import ChatMessage
from src.core.domain.session import LoopDetectionConfiguration, Session, SessionState
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.command_processor import CommandProcessor as CoreCommandProcessor


async def run_command(command_string: str) -> str:

    class _SessionSvc(ISessionService):
        async def get_session(self, session_id: str) -> Session:
            return Session(
                session_id=session_id,
                state=SessionState(loop_config=LoopDetectionConfiguration()),
            )

        async def get_session_async(self, session_id: str) -> Session:
            return await self.get_session(session_id)

        async def create_session(self, session_id: str) -> Session:
            return Session(session_id=session_id)

        async def get_or_create_session(self, session_id: str | None = None) -> Session:
            if session_id is None:
                # This should ideally create a new session ID or handle it as per the actual service
                return Session(session_id="new_session_id")
            return await self.get_session(session_id)

        async def update_session(self, session: Session) -> None:
            pass

        async def update_session_backend_config(
            self, session_id: str, backend_type: str, model: str
        ) -> None:
            pass

        async def delete_session(self, session_id: str) -> bool:
            return True

        async def get_all_sessions(self) -> list[Session]:
            return []

    # Use the actual NewCommandService
    command_service = NewCommandService(
        session_service=_SessionSvc(), command_parser=CommandParser()
    )

    processor = CoreCommandProcessor(command_service)
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
