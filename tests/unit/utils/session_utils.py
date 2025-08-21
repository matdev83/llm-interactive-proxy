"""Utility functions for session state management in tests.

This module provides utility functions for managing session state in tests,
ensuring consistent behavior across all tests.
"""

import gc
from typing import Optional, cast

from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.domain.session import Session, SessionState, SessionStateAdapter


def update_session_state(
    session: Session, 
    backend_type: Optional[str] = None,
    model: Optional[str] = None,
    project: Optional[str] = None,
    hello_requested: Optional[bool] = None,
    interactive_mode: Optional[bool] = None,
) -> None:
    """Update the session state with the given values.
    
    This function updates the session state with the given values,
    ensuring that the session state is properly updated in the session object.
    
    Args:
        session: The session to update
        backend_type: The backend type to set
        model: The model to set
        project: The project to set
        hello_requested: Whether hello was requested
        interactive_mode: Whether interactive mode is enabled
    """
    # Get the current state
    current_state = session.state
    
    # Update the backend configuration if needed
    if backend_type is not None or model is not None:
        new_backend_config = current_state.backend_config
        
        if backend_type is not None:
            new_backend_config = new_backend_config.with_backend(backend_type)
        
        if model is not None:
            new_backend_config = new_backend_config.with_model(model)
        
        current_state = current_state.with_backend_config(cast(BackendConfiguration, new_backend_config))
    
    # Update the project if needed
    if project is not None:
        current_state = current_state.with_project(project)
    
    # Update hello_requested if needed
    if hello_requested is not None:
        current_state = current_state.with_hello_requested(hello_requested)
    
    # Update interactive_mode if needed
    if interactive_mode is not None:
        new_backend_config = current_state.backend_config
        new_backend_config = new_backend_config.with_interactive_mode(interactive_mode)
        current_state = current_state.with_backend_config(cast(BackendConfiguration, new_backend_config))
    
    # Update the session state
    session.state = current_state


def find_session_by_state(state: SessionStateAdapter) -> Optional[Session]:
    """Find the session that contains the given state.
    
    This function searches for a session that contains the given state,
    which is useful for updating the session state when only the state is available.
    
    Args:
        state: The state to search for
        
    Returns:
        The session that contains the given state, or None if not found
    """
    for session_obj in [obj for obj in gc.get_objects() if isinstance(obj, Session)]:
        if session_obj.state is state:
            return session_obj
    
    return None


def update_state_in_session(
    state: SessionStateAdapter,
    backend_type: Optional[str] = None,
    model: Optional[str] = None,
    project: Optional[str] = None,
    hello_requested: Optional[bool] = None,
    interactive_mode: Optional[bool] = None,
) -> None:
    """Update the session state with the given values.
    
    This function updates the session state with the given values,
    finding the session that contains the given state and updating it.
    
    Args:
        state: The state to update
        backend_type: The backend type to set
        model: The model to set
        project: The project to set
        hello_requested: Whether hello was requested
        interactive_mode: Whether interactive mode is enabled
    """
    # Find the session that contains the given state
    session = find_session_by_state(state)
    
    if session:
        # Update the session state
        update_session_state(
            session,
            backend_type=backend_type,
            model=model,
            project=project,
            hello_requested=hello_requested,
            interactive_mode=interactive_mode,
        )
    else:
        # If the session was not found, we can't update the state
        # This is a no-op
        pass
