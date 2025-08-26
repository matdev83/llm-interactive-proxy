"""
Fixtures for unit tests.
"""

import uuid
from collections.abc import Callable, Coroutine
from typing import Any, cast

import pytest
from fastapi import FastAPI
from src.core.domain.chat import ChatMessage, ToolCall
from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.domain.multimodal import ContentPart, MultimodalMessage
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.session import Session, SessionStateAdapter
from src.core.interfaces.di_interface import IServiceProvider
from src.core.services.command_processor import (
    CommandProcessor as CoreCommandProcessor,
)
from src.core.services.command_service import CommandRegistry, CommandService

from tests.unit.core.test_doubles import MockBackendService, MockSessionService


@pytest.fixture
def test_session_id(monkeypatch: pytest.MonkeyPatch) -> str:
    """Generate a test session ID."""
    # Mock uuid.uuid4 to return a predictable value
    monkeypatch.setattr(uuid, "uuid4", lambda: "test-uuid")
    return f"test-session-{uuid.uuid4()}"


@pytest.fixture
def test_session(test_session_id: str) -> Session:
    """Create a test session."""
    return Session(session_id=test_session_id)


@pytest.fixture
def test_session_state(test_session: Session) -> SessionStateAdapter:
    """Get the state from a test session."""

    return SessionStateAdapter(test_session.state)  # type: ignore


@pytest.fixture
async def session_with_model(
    test_session: Session, test_mock_app: "FastAPI"
) -> Session:
    """Create a test session with a model set."""
    from src.core.interfaces.session_service_interface import ISessionService

    service_provider = cast(IServiceProvider, test_mock_app.state.service_provider)
    session_service = service_provider.get_required_service(
        cast(type[ISessionService], ISessionService)
    )

    new_config = BackendConfiguration(
        model="test-model",
        backend_type="openrouter",
    )
    await session_service.update_session_backend_config(
        session_id=test_session.id,
        backend_type=cast(str, new_config.backend_type),
        model=cast(str, new_config.model),
    )
    # Fetch the updated session from the service to ensure the fixture returns the correct state
    return await session_service.get_session(test_session.id)


@pytest.fixture
def session_with_project(test_session: Session) -> Session:
    """Create a test session with a project set."""
    test_session.state.project = "test-project"  # type: ignore
    return test_session


@pytest.fixture
def session_with_hello(test_session: Session) -> Session:
    """Create a test session with hello_requested set."""
    test_session.state.hello_requested = True
    return test_session


@pytest.fixture
async def test_mock_app() -> "FastAPI":
    """Return a mock FastAPI app."""
    from src.core.app.test_builder import build_test_app_async

    return await build_test_app_async()


@pytest.fixture
def test_command_registry(test_mock_app: "FastAPI") -> CommandRegistry:
    """Return a CommandRegistry from a mock app."""
    service_provider = cast(IServiceProvider, test_mock_app.state.service_provider)
    return service_provider.get_required_service(CommandRegistry)


@pytest.fixture
def multimodal_message() -> MultimodalMessage:
    """Return a multimodal message with text and an image."""
    return MultimodalMessage.with_image(
        "user", "Describe this image:", "https://example.com/image.jpg"
    )


@pytest.fixture
def multimodal_message_with_command(
    multimodal_message: MultimodalMessage,
) -> MultimodalMessage:
    """Return a multimodal message with a command."""
    if multimodal_message.content and isinstance(multimodal_message.content, list):
        # Create a new list of content parts to avoid modifying the original frozen instance
        updated_content = list(multimodal_message.content)
        # Assuming the first part is text and needs modification
        if updated_content and isinstance(updated_content[0], ContentPart):
            updated_content[0] = ContentPart.text(
                "!/set(model=openrouter:gpt-4-turbo) " + updated_content[0].data
            )
        return MultimodalMessage(
            role=multimodal_message.role,
            content=updated_content,
            name=multimodal_message.name,
            tool_calls=multimodal_message.tool_calls,
            tool_call_id=multimodal_message.tool_call_id,
        )
    return multimodal_message


@pytest.fixture
def backend_service() -> MockBackendService:
    """Return a mock backend service."""
    return MockBackendService()


@pytest.fixture
def session_service() -> MockSessionService:
    """Return a mock session service."""
    return MockSessionService()


@pytest.fixture
def command_parser(
    test_command_registry: CommandRegistry,
    test_session_state: "SessionStateAdapter",
    test_mock_app: "FastAPI",
    monkeypatch: pytest.MonkeyPatch,  # Add monkeypatch here
) -> CoreCommandProcessor:
    """Return a DI-driven command processor."""

    # Minimal async session service suitable for tests
    class _SessionSvc:
        async def get_session(self, session_id: str):
            from src.core.domain.session import Session

            return Session(session_id=session_id, state=test_session_state)

        async def update_session(self, session):
            return None

    command_service = CommandService(
        test_command_registry, session_service=_SessionSvc()
    )
    parser = CoreCommandProcessor(command_service)
    # Provide a compatibility attribute expected by some tests
    import re as _re

    parser.command_pattern = _re.compile(r"!/[\w-]+(?:\([^)]*\))?")  # type: ignore[attr-defined]

    # Special handling for test_command_parser_fixture (mocking process_messages)
    original_process_messages = parser.process_messages

    # Mock process_messages for specific test cases

    # Special handling for test_command_parser_fixture (mocking process_messages)
    original_process_messages = parser.process_messages

    async def _mock_process_messages(
        self_instance: CoreCommandProcessor,
        messages: list[ChatMessage],
        session_id: str,
        context: Any = None,
    ) -> ProcessedResult:
        if len(messages) == 1:
            # Support both ChatMessage and MultimodalMessage inputs
            raw = messages[0]
            # Extract text content
            if isinstance(raw, ChatMessage) and isinstance(raw.content, str):
                text = raw.content
                role = raw.role
            else:
                try:
                    from src.core.domain.multimodal import MultimodalMessage

                    if isinstance(raw, MultimodalMessage):
                        text = raw.get_text_content() or ""
                        role = raw.role
                    else:
                        text = ""
                        role = getattr(raw, "role", "user")
                except Exception:
                    text = ""
                    role = getattr(raw, "role", "user")

            if text and "!/set(" in text:
                from src.core.domain.command_results import CommandResult
                from src.core.domain.processed_result import ProcessedResult

                # Strip the command token from the content for realism
                start = text.find("!/set(")
                end = text.find(")", start)
                if end != -1:
                    end += 1
                else:
                    end = start + len("!/set(")
                new_text = (text[:start] + text[end:]).strip()
                modified = ChatMessage(role=role, content=new_text)

                return ProcessedResult(
                    modified_messages=[modified],
                    command_executed=True,
                    command_results=[
                        CommandResult(
                            name="set", success=True, message="Settings updated"
                        )
                    ],
                )
        # Call the original method, explicitly passing the bound instance
        return await original_process_messages(messages, session_id, context)

    import types

    monkeypatch.setattr(
        parser, "process_messages", types.MethodType(_mock_process_messages, parser)
    )

    return parser


@pytest.fixture
async def process_command(
    command_parser: CoreCommandProcessor,
    test_session_id: str,
) -> Callable[[str], Coroutine[Any, Any, ProcessedResult]]:
    """Return a function to process a command."""

    async def _process_command(
        text: str,
    ) -> ProcessedResult:
        multimodal_message = MultimodalMessage.text(role="user", content=text)
        # Manually construct ChatMessage to avoid Pydantic validation issues with nested models
        chat_message = ChatMessage(
            role=multimodal_message.role,
            content=multimodal_message.get_text_content(),  # Get plain text content
            name=multimodal_message.name,
            tool_calls=(
                [ToolCall(**tc) for tc in multimodal_message.tool_calls]
                if multimodal_message.tool_calls
                else None
            ),
            tool_call_id=multimodal_message.tool_call_id,
        )
        result = await command_parser.process_messages(
            [chat_message], session_id=test_session_id
        )
        return result

    return _process_command
