import pytest
from unittest.mock import patch

from src.core.commands.handlers.unset_handler import UnsetCommandHandler
from src.core.domain.session import Session, SessionState, SessionStateAdapter


@pytest.mark.asyncio
async def test_unset_project_dir_direct():
    """Test that the UnsetCommandHandler can directly unset project_dir."""
    # Create a session state with a project dir
    state = SessionState(project_dir="/some/path")
    adapter = SessionStateAdapter(state)
    
    # Verify initial state
    assert adapter.project_dir == "/some/path"
    
    # Create the handler
    handler = UnsetCommandHandler()
    
    # Call the handler directly
    result = handler.handle(["project-dir"], {}, adapter)
    
    # Verify the result
    assert result.success is True
    assert result.new_state is not None
    
    # Verify the project_dir is None
    assert result.new_state.project_dir is None
    
    # Also verify the original adapter was updated
    assert adapter.project_dir is None
