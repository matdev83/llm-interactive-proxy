
import pytest
from unittest.mock import Mock, MagicMock
from src.core.domain.commands.set_command import SetCommand
from src.core.domain.session import Session, SessionState, BackendConfiguration, ReasoningConfiguration

@pytest.mark.asyncio
async def test_set_temperature_unit():
    """
    Unit test for the SetCommand focusing on changing the temperature.
    This test verifies the state change directly, not the output message.
    """
    # Arrange
    command = SetCommand()
    
    # Create an initial session state
    initial_reasoning_config = ReasoningConfiguration(temperature=0.5)
    initial_backend_config = BackendConfiguration(backend_type="test", model="test")
    initial_state = SessionState(backend_config=initial_backend_config, reasoning_config=initial_reasoning_config)
    
    # Create a mock session object
    mock_session = Mock(spec=Session)
    mock_session.state = initial_state
    
    args = {"temperature": "0.8"}
    
    # Act
    result = await command.execute(args, mock_session)
    
    # Assert
    assert result.success is True
    assert result.new_state is not None
    
    # Verify that the new state has the updated temperature
    final_state = result.new_state
    assert final_state.reasoning_config.temperature == 0.8
    
    # Verify that other parts of the state remain unchanged
    assert final_state.backend_config.backend_type == "test"

