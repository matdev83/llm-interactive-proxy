import pytest
from src.core.domain.session import SessionState


async def run_command(command_string: str) -> str:
    from src.core.domain.commands.project_command import ProjectCommand

    state = SessionState()
    # parse args like !/project(name=abc)
    args: dict[str, object] = {}
    if "(" in command_string and ")" in command_string:
        arg_part = command_string.split("(", 1)[1].rsplit(")", 1)[0]
        if "=" in arg_part:
            key, value = arg_part.split("=", 1)
            args[key.strip()] = value.strip()

    class _Session:
        def __init__(self, state: SessionState) -> None:
            self.state = state

    result = await ProjectCommand().execute(args, _Session(state))
    return getattr(result, "message", "")


@pytest.mark.asyncio
async def test_project_success_snapshot(snapshot):
    """Snapshot test for a successful project command."""
    command_string = "!/project(name=my-awesome-project)"
    output_message = await run_command(command_string)
    snapshot.assert_match(output_message, "project_success_output")


@pytest.mark.asyncio
async def test_project_failure_snapshot(snapshot):
    """Snapshot test for a failing project command."""
    command_string = "!/project(name=)"
    output_message = await run_command(command_string)
    snapshot.assert_match(output_message, "project_failure_output")
