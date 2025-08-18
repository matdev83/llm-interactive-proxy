from src.core.commands.unset_command import UnsetCommand
from src.core.domain.session import Session, SessionState, SessionStateAdapter
import asyncio

async def test_unset_command_with_model():
    # Create a session with a model set
    sess = Session('test')
    initial_state = SessionStateAdapter(SessionState())
    print(f"Initial state model: {initial_state.backend_config.model}")
    
    # Set a model first
    backend_config_with_model = initial_state.backend_config.with_model("gpt-4")
    print(f"Backend config with model: {backend_config_with_model.model}")
    
    state_with_model = initial_state.with_backend_config(backend_config_with_model)
    print(f"State with model backend config: {state_with_model.backend_config.model}")
    
    sess.state = state_with_model
    print(f"Session state model: {sess.state.backend_config.model}")
    
    # Test unsetting the model - this is how unset command should be called
    # With positional arguments like unset(model, project)
    cmd = UnsetCommand()
    
    # This simulates !/unset(model) - the parser would convert this to {'0': 'model'}
    result = await cmd.execute({'0': 'model'}, sess)
    
    print(f"Unset command result - Success: {result.success}")
    print(f"Unset command result - Message: {result.message}")
    print(f"Unset command result - Model after unset: {sess.state.backend_config.model}")
    
    print("Test completed!")
    return result

if __name__ == "__main__":
    asyncio.run(test_unset_command_with_model())