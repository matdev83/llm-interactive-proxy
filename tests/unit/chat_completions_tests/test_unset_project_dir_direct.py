import pytest
from src.core.commands.unset_command import UnsetCommand
from src.core.domain.session import Session, SessionState, SessionStateAdapter


@pytest.mark.asyncio
async def test_unset_project_dir_direct():
    """Test that the UnsetCommand can directly unset project_dir."""
    # Create a session state with a project dir
    state = SessionState(project_dir="/some/path")
    session = Session(session_id="test", state=state)

    # Verify initial state
    assert session.state.project_dir == "/some/path"

    # Create the command
    command = UnsetCommand()

    # Call the command directly
    result = await command.execute({"project-dir": True}, session)

    # Verify the result
    assert result.success is True
    assert result.new_state is not None

    # Verify the project_dir is None in the new state
    assert result.new_state.project_dir is None

    # Create a new adapter with the new state
    if isinstance(result.new_state, SessionStateAdapter):
        # If the result is already an adapter, use its internal state
        adapter = result.new_state
    else:
        # Otherwise create a new adapter with the result
        adapter = SessionStateAdapter(result.new_state)

    # Now verify the adapter has project_dir=None
    assert adapter.project_dir is None
