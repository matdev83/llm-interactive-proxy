"""
Property-based tests for InitHandler.

Feature: codebuff-backend-compatibility
Tests correctness properties for session initialization.
"""

from unittest.mock import MagicMock

import pytest
from hypothesis import given
from hypothesis import strategies as st
from src.codebuff.connection_manager import ConnectionManager
from src.codebuff.handlers.init_handler import InitHandler
from src.codebuff.schemas import InitAction


# Strategy for generating file contexts
@st.composite
def file_context_strategy(draw):
    """Generate a file context dictionary."""
    num_files = draw(st.integers(min_value=0, max_value=10))
    file_context = {}
    for _ in range(num_files):
        # Use printable ASCII to avoid Unicode encoding issues in parallel test execution
        filename = draw(
            st.text(
                min_size=1,
                max_size=50,
                alphabet=st.characters(min_codepoint=32, max_codepoint=126),
            )
        )
        content = draw(
            st.text(
                min_size=0,
                max_size=200,
                alphabet=st.characters(min_codepoint=32, max_codepoint=126),
            )
        )
        file_context[filename] = {"content": content}
    return file_context


@pytest.mark.asyncio
@given(
    session_id=st.text(
        min_size=1,
        max_size=100,
        alphabet=st.characters(min_codepoint=32, max_codepoint=126),
    ),
    fingerprint_id=st.text(
        min_size=1,
        max_size=100,
        alphabet=st.characters(min_codepoint=32, max_codepoint=126),
    ),
    file_context=file_context_strategy(),
)
async def test_property_17_file_context_storage(
    session_id, fingerprint_id, file_context
):
    """
    Feature: codebuff-backend-compatibility, Property 17: File context storage
    Validates: Requirements 5.1

    For any init action with file context, the system should store that context
    in the session.
    """
    # Arrange
    connection_manager = ConnectionManager()
    init_handler = InitHandler(connection_manager)
    websocket = MagicMock()

    # Register the connection
    await connection_manager.connect(websocket, session_id)

    # Create init action
    init_action = InitAction(
        type="init",
        fingerprintId=fingerprint_id,
        authToken=None,
        fileContext=file_context,
        repoUrl=None,
    )

    # Act
    await init_handler.handle_init(websocket, init_action)

    # Assert - file context should be stored in session
    session = await connection_manager.get_session(websocket)
    assert session is not None
    assert session.file_context == file_context


@pytest.mark.asyncio
@given(
    session_id=st.text(
        min_size=1,
        max_size=100,
        alphabet=st.characters(min_codepoint=32, max_codepoint=126),
    ),
    fingerprint_id=st.text(
        min_size=1,
        max_size=100,
        alphabet=st.characters(min_codepoint=32, max_codepoint=126),
    ),
    file_context=file_context_strategy(),
)
async def test_property_18_file_context_persistence(
    session_id, fingerprint_id, file_context
):
    """
    Feature: codebuff-backend-compatibility, Property 18: File context persistence
    Validates: Requirements 5.3

    For any session with stored file context, subsequent operations should have
    access to that context.
    """
    # Arrange
    connection_manager = ConnectionManager()
    init_handler = InitHandler(connection_manager)
    websocket = MagicMock()

    # Register the connection
    await connection_manager.connect(websocket, session_id)

    # Create and handle init action
    init_action = InitAction(
        type="init",
        fingerprintId=fingerprint_id,
        authToken=None,
        fileContext=file_context,
        repoUrl=None,
    )
    await init_handler.handle_init(websocket, init_action)

    # Act - retrieve session multiple times
    session1 = await connection_manager.get_session(websocket)
    session2 = await connection_manager.get_session(websocket)

    # Assert - file context should persist across retrievals
    assert session1 is not None
    assert session2 is not None
    assert session1.file_context == file_context
    assert session2.file_context == file_context
    assert session1.file_context is session2.file_context  # Same object
