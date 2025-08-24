import pytest
from src.core.domain.session import BackendConfiguration, SessionState


async def run_command(command_string: str) -> str:
    from src.core.domain.commands.oneoff_command import OneoffCommand

    state = SessionState(backend_config=BackendConfiguration())
    args: dict[str, object] = {}
    if "(" in command_string and ")" in command_string:
        arg_part = command_string.split("(", 1)[1].rsplit(")", 1)[0]
        if arg_part:
            # Pass as a flag-style key consumed by OneoffCommand
            args[arg_part.strip()] = True

    class _Session:
        def __init__(self, state: SessionState) -> None:
            self.state = state

    result = await OneoffCommand().execute(args, _Session(state))
    return getattr(result, "message", "")


@pytest.mark.asyncio
async def test_oneoff_success_snapshot(snapshot):
    """Snapshot test for a successful oneoff command."""
    command_string = "!/oneoff(gemini/gemini-pro)"
    output_message = await run_command(command_string)
    snapshot.assert_match(output_message, "oneoff_success_output")


@pytest.mark.asyncio
async def test_oneoff_failure_snapshot(snapshot):
    """Snapshot test for a failing oneoff command."""
    command_string = "!/oneoff(invalid-format)"
    output_message = await run_command(command_string)
    snapshot.assert_match(output_message, "oneoff_failure_output")
