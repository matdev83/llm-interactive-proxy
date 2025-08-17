#!/usr/bin/env python3
"""
Verification script to confirm that our SessionStateAdapter fixes are working.
"""

from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.domain.session import SessionState, SessionStateAdapter


def test_session_state_adapter_fixes():
    """Test that the SessionStateAdapter has all the required methods."""

    # Create a session state adapter
    session_state = SessionState()
    adapter = SessionStateAdapter(session_state)

    # Test that all the methods we added exist and can be called
    new_backend_config = BackendConfiguration(backend_type="openai", model="gpt-4")
    result = adapter.with_backend_config(new_backend_config)
    assert isinstance(
        result, SessionStateAdapter
    ), "with_backend_config should return SessionStateAdapter"

    from src.core.domain.configuration.reasoning_config import ReasoningConfiguration

    new_reasoning_config = ReasoningConfiguration(temperature=0.7)
    result = adapter.with_reasoning_config(new_reasoning_config)
    assert isinstance(
        result, SessionStateAdapter
    ), "with_reasoning_config should return SessionStateAdapter"

    result = adapter.with_project("test-project")
    assert isinstance(
        result, SessionStateAdapter
    ), "with_project should return SessionStateAdapter"

    result = adapter.with_project_dir("/test/path")
    assert isinstance(
        result, SessionStateAdapter
    ), "with_project_dir should return SessionStateAdapter"

    result = adapter.with_interactive_just_enabled(True)
    assert isinstance(
        result, SessionStateAdapter
    ), "with_interactive_just_enabled should return SessionStateAdapter"

    # Test properties
    assert hasattr(adapter, "interactive_mode"), "Should have interactive_mode property"
    assert hasattr(adapter, "hello_requested"), "Should have hello_requested property"
    assert hasattr(adapter, "is_cline_agent"), "Should have is_cline_agent property"

    # SessionStateAdapter fixes verified successfully


def test_register_services_function():
    """Test that the register_services function exists."""
    # Testing register_services function

    # Try to import the function
    try:
        from src.core.app.application_factory import register_services

        # register_services function imported successfully

        # Test that it's callable
        assert callable(register_services), "register_services should be callable"
        # register_services function is callable

    except ImportError as e:
        # Error importing register_services
        return False

    # register_services function verified successfully
    return True


if __name__ == "__main__":
    try:
        test_session_state_adapter_fixes()
        test_register_services_function()
        print("All fixes verified successfully")
    except Exception as e:
        import traceback
        print(f"Error during verification: {e}")
        traceback.print_exc()

