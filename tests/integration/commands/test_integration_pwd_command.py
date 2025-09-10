import pytest
from src.core.domain.session import SessionState


async def run_command(initial_state: SessionState) -> str:
    from src.core.domain.commands.pwd_command import PwdCommand

    # Create minimal Session wrapper
    class _Session:
        def __init__(self, state: SessionState) -> None:
            self.state = state

    result = await PwdCommand().execute({}, _Session(initial_state))
    return getattr(result, "message", "")


@pytest.mark.asyncio
async def test_pwd_with_dir_set_snapshot(snapshot):
    """Snapshot test for the pwd command when a directory is set."""
    initial_state = SessionState(project_dir="/path/to/a/cool/project")
    output_message = await run_command(initial_state)
    snapshot.assert_match(output_message, "pwd_with_dir_output")


@pytest.mark.asyncio
async def test_pwd_with_dir_not_set_snapshot(snapshot):
    """Snapshot test for the pwd command when no directory is set."""
    initial_state = SessionState(project_dir=None)
    output_message = await run_command(initial_state)
    snapshot.assert_match(output_message, "pwd_without_dir_output")
