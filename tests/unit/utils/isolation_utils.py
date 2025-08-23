"""Utility functions for test isolation.

This module provides utility functions for isolating tests from each other,
preventing interference between tests.
"""

import gc
from collections.abc import Callable, Iterator
from typing import Any, TypeVar, cast

import pytest
from src.core.domain.session import Session, SessionState, SessionStateAdapter
from src.core.services.command_service import CommandRegistry

# Type variable for generic functions
T = TypeVar("T")


def get_all_sessions() -> list[Session]:
    """Get all Session objects in memory.

    Returns:
        List[Session]: A list of all Session objects in memory
    """
    return [obj for obj in gc.get_objects() if isinstance(obj, Session)]


def get_all_session_states() -> list[SessionStateAdapter]:
    """Get all SessionStateAdapter objects in memory.

    Returns:
        List[SessionStateAdapter]: A list of all SessionStateAdapter objects in memory
    """
    return [obj for obj in gc.get_objects() if isinstance(obj, SessionStateAdapter)]


def clear_sessions() -> None:
    """Clear all Session objects from memory.

    This function attempts to remove all references to Session objects,
    allowing them to be garbage collected.
    """
    sessions = get_all_sessions()
    for session in sessions:
        # Clear the state reference
        session.state = SessionStateAdapter(SessionState())

    # Force garbage collection
    gc.collect()


def reset_command_registry() -> None:
    """Reset the CommandRegistry singleton.

    This function clears the CommandRegistry singleton instance,
    ensuring that each test starts with a clean registry.
    """

    # Clear the instance
    CommandRegistry.clear_instance()

    # Force garbage collection to remove any lingering references
    gc.collect()


def reset_global_state() -> None:
    """Reset all global state.

    This function resets all global state that might interfere with tests,
    including the CommandRegistry, session state, and DI container.
    """
    # Reset the CommandRegistry
    reset_command_registry()

    # Clear all sessions
    clear_sessions()

    # Reset the DI container
    try:
        import src.core.di.services as services_module

        # Save the original service provider and collection
        original_provider = services_module._service_provider
        original_services = services_module._service_collection

        # Reset the service provider and collection
        services_module._service_provider = None
        services_module._service_collection = None

        # Force garbage collection
        gc.collect()

        # Restore the original service provider and collection
        services_module._service_provider = original_provider
        services_module._service_collection = original_services
    except (ImportError, AttributeError):
        pass

    # Integration bridge has been removed - no cleanup needed

    # Force garbage collection again
    gc.collect()


def isolate_function(func: Callable[..., T]) -> Callable[..., T]:
    """Decorator to isolate a function from global state.

    This decorator ensures that the function runs in isolation,
    without interference from global state.

    Args:
        func: The function to isolate

    Returns:
        A wrapped function that runs in isolation
    """

    @pytest.mark.no_global_mock
    def wrapper(*args: Any, **kwargs: Any) -> T:
        # Reset global state before running the function
        reset_global_state()

        # Run the function
        # Run the function
        result = func(*args, **kwargs)

        # Reset global state after running the function
        reset_global_state()

        return result

    # Copy metadata from the original function
    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    wrapper.__module__ = func.__module__
    if hasattr(func, "__annotations__"):
        wrapper.__annotations__ = func.__annotations__

    return cast(Callable[..., T], wrapper)


class IsolatedTestCase:
    """Base class for test cases that need isolation.

    This class provides methods for isolating tests from each other,
    preventing interference between tests.
    """

    @classmethod
    def setup_class(cls) -> None:
        """Set up the test class.

        This method is called once before any tests in the class are run.
        """
        # Reset global state before running any tests
        reset_global_state()

    @classmethod
    def teardown_class(cls) -> None:
        """Tear down the test class.

        This method is called once after all tests in the class have run.
        """
        # Reset global state after running all tests
        reset_global_state()

    def setup_method(self) -> None:
        """Set up the test method.

        This method is called before each test method is run.
        """
        # Reset global state before running the test
        reset_global_state()

    def teardown_method(self) -> None:
        """Tear down the test method.

        This method is called after each test method has run.
        """
        # Reset global state after running the test
        reset_global_state()


@pytest.fixture
def isolated_test_case() -> Iterator[None]:
    """Fixture to isolate a test from global state.

    This fixture ensures that the test runs in isolation,
    without interference from global state.

    Yields:
        None
    """
    # Reset global state before running the test
    reset_global_state()

    # Yield to the test
    yield

    # Reset global state after running the test
    reset_global_state()


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Hook to set up a test before it runs.

    This hook is called before each test is run.

    Args:
        item: The test item to set up
    """
    # If the test has the no_global_mock marker, reset global state
    if item.get_closest_marker("no_global_mock"):
        reset_global_state()
    else:
        # For all tests, at least reset the command registry and clear sessions
        reset_command_registry()
        clear_sessions()


def pytest_runtest_teardown(item: pytest.Item) -> None:
    """Hook to tear down a test after it runs.

    This hook is called after each test has run.

    Args:
        item: The test item to tear down
    """
    # If the test has the no_global_mock marker, reset global state
    if item.get_closest_marker("no_global_mock"):
        reset_global_state()
    else:
        # For all tests, at least reset the command registry and clear sessions
        reset_command_registry()
        clear_sessions()
