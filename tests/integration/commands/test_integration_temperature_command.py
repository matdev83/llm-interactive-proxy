
import pytest
from src.core.domain.session import ReasoningConfiguration, SessionState


async def run_command(command_string: str) -> str:
    from src.core.domain.commands.temperature_command import TemperatureCommand

    # create session state
    state = SessionState(reasoning_config=ReasoningConfiguration())

    # parse args from command string like !/temperature(value=0.9)
    args: dict[str, object] = {}
    if "(" in command_string and ")" in command_string:
        arg_part = command_string.split("(", 1)[1].rsplit(")", 1)[0]
        if "=" in arg_part:
            key, value = arg_part.split("=", 1)
            args[key.strip()] = value.strip()

    cmd = TemperatureCommand()
    # TemperatureCommand expects a Session-like object; build minimal
    class _Session:
        def __init__(self, state: SessionState) -> None:
            self.state = state

    result = await cmd.execute(args, _Session(state))
    return getattr(result, "message", "")


@pytest.mark.asyncio
async def test_temperature_success_snapshot(snapshot):
    """Snapshot test for a successful temperature command."""
    command_string = "!/temperature(value=0.9)"
    output_message = await run_command(command_string)
    snapshot.assert_match(output_message, "temperature_success_output")


@pytest.mark.asyncio
async def test_temperature_failure_snapshot(snapshot):
    """Snapshot test for a failing temperature command."""
    command_string = "!/temperature(value=invalid)"
    output_message = await run_command(command_string)
    snapshot.assert_match(output_message, "temperature_failure_output")
