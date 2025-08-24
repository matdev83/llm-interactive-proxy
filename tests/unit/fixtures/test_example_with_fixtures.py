"""Example tests using the new fixtures.

This module demonstrates how to use the new fixtures.
"""

from collections.abc import Awaitable, Callable

import pytest
from fastapi import FastAPI
from src.core.domain.multimodal import ContentPart, ContentType, MultimodalMessage
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.session import Session
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.command_processor_interface import ICommandProcessor

# Mark all tests in this module as isolated
pytestmark = pytest.mark.no_global_mock


@pytest.mark.command
@pytest.mark.asyncio
async def test_process_command_with_fixtures(
    process_command: Callable[[str], Awaitable[ProcessedResult]],
) -> None:
    """Test processing a command using the process_command fixture."""
    text = "!/set(model=openrouter:gpt-4-turbo) Please use this model"
    result = await process_command(text)
    commands_found = result.command_executed
    processed_text = result.command_results[0].message if result.command_results else ""

    # Verify the command was found and processed
    assert commands_found

    # Verify the command was stripped from the message
    # Note: The exact behavior depends on the implementation of process_commands_in_messages_test
    # With the current implementation, the command is removed but surrounding text is preserved
    assert "!/set" not in processed_text


@pytest.mark.session
@pytest.mark.skip("Skipping until BackendConfiguration property issues are resolved")
def test_session_with_model_fixture() -> None:
    """Test creating a session with model and backend type."""
    # Create a session directly with the desired configuration
    from src.core.domain.configuration.backend_config import BackendConfiguration
    from src.core.domain.session import Session, SessionState

    # Create a backend configuration with the desired values
    backend_config = BackendConfiguration(
        backend_type_value="openrouter", model_value="test-model"
    )

    # Create a session state with the backend configuration
    state = SessionState(backend_config=backend_config)

    # Create a session with the state
    session = Session(session_id="test-session", state=state)

    # Print the values to debug
    print(f"Backend config model: {backend_config.model}")
    print(f"Backend config backend_type: {backend_config.backend_type}")
    print(f"Backend config model_value: {backend_config.model_value}")
    print(f"Backend config backend_type_value: {backend_config.backend_type_value}")

    print(f"Session state backend config model: {session.state.backend_config.model}")
    print(
        f"Session state backend config backend_type: {session.state.backend_config.backend_type}"
    )
    print(
        f"Session state backend config model_value: {session.state.backend_config.model_value}"
    )
    print(
        f"Session state backend config backend_type_value: {session.state.backend_config.backend_type_value}"
    )

    # Verify the model and backend are set correctly using the value fields directly
    assert session.state.backend_config.model_value == "test-model"
    assert session.state.backend_config.backend_type_value == "openrouter"


@pytest.mark.session
def test_session_with_project_fixture(session_with_project: Session) -> None:
    """Test the session_with_project fixture."""
    # Verify the project is set correctly
    assert session_with_project.state.project == "test-project"


@pytest.mark.backend
@pytest.mark.asyncio
async def test_backend_service_fixture(backend_service: IBackendService) -> None:
    """Test the backend_service fixture."""
    # Since we're mocking the backend, we'll just check that we can access it
    assert backend_service is not None

    # The backend_service fixture now returns a MockBackendService,
    # which has predefined behavior for get_available_models.
    is_valid, error_message = await backend_service.validate_backend_and_model(
        "openrouter", "test-model"
    )
    assert is_valid
    assert error_message is None


@pytest.mark.command
@pytest.mark.asyncio
async def test_command_parser_fixture(
    command_parser: ICommandProcessor,
    test_mock_app: FastAPI,
    test_session_id: str,
) -> None:
    """Test the command_parser fixture."""
    # Create a message with a command
    message = MultimodalMessage.text(
        role="user", content="!/set(model=openrouter:test-model)"
    )

    # Process the message
    result = await command_parser.process_messages(
        [message], session_id=test_session_id
    )

    # Verify the command was found
    assert result.command_executed

    # Verify the command parser is properly initialized
    assert hasattr(command_parser, "command_pattern")
    assert hasattr(command_parser, "config")


@pytest.mark.di
@pytest.mark.multimodal
def test_multimodal_message_fixture(multimodal_message: MultimodalMessage) -> None:
    """Test the multimodal_message fixture."""
    # Verify the message has both text and image parts
    assert isinstance(multimodal_message.content, list)
    assert len(multimodal_message.content) == 2

    # Verify the first part is text
    assert multimodal_message.content[0].type == ContentPart.text("").type
    assert multimodal_message.content[0].data == "Describe this image:"

    # Verify the second part is an image
    assert multimodal_message.content[1].type == ContentPart.image_url("").type
    assert multimodal_message.content[1].data == "https://example.com/image.jpg"

    # Verify the overall type of content is List[ContentPart]
    assert isinstance(multimodal_message.content, list)
    for part in multimodal_message.content:
        assert isinstance(part, ContentPart)


@pytest.mark.di
@pytest.mark.command
@pytest.mark.multimodal
@pytest.mark.asyncio
async def test_multimodal_message_with_command_fixture(
    multimodal_message_with_command: MultimodalMessage,
    process_command: Callable[[str], Awaitable[ProcessedResult]],
) -> None:
    """Test the multimodal_message_with_command fixture with process_command."""
    # Extract the content from the multimodal message
    # Assuming the command is always in the first text part
    text_part = None
    if multimodal_message_with_command.content is not None:
        text_part = next(
            (
                p
                for p in multimodal_message_with_command.content
                if isinstance(p, ContentPart) and p.type == ContentType.TEXT
            ),
            None,
        )
    assert text_part is not None and text_part.type == ContentType.TEXT

    # Process the command in the text part
    result = await process_command(text_part.data)
    commands_found = result.command_executed

    # Verify the command was found and processed
    assert commands_found
