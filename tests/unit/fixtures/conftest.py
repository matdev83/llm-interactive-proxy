"""
Fixtures for unit tests.
"""

import uuid
from collections.abc import Callable, Coroutine
from typing import Any, cast

import pytest
from fastapi import FastAPI
from src.core.domain.chat import ChatMessage
from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.domain.multimodal import ContentPart, MultimodalMessage
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.session import Session, SessionStateAdapter
from src.core.interfaces.command_service_interface import ICommandService
from src.core.interfaces.di_interface import IServiceProvider
from src.core.services.command_processor import (
    CommandProcessor as CoreCommandProcessor,
)

from tests.unit.core.test_doubles import MockBackendService, MockSessionService
from tests.utils.command_service_utils import build_new_command_service


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
    # Lazy import to avoid heavy initialization during collection
    from src.core.app.test_builder import build_test_app_async

    return await build_test_app_async()


@pytest.fixture
def test_command_service(test_mock_app: "FastAPI") -> ICommandService:
    """Return a ICommandService from a mock app."""
    service_provider = cast(IServiceProvider, test_mock_app.state.service_provider)
    return service_provider.get_required_service(ICommandService)


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
                f"{updated_content[0].data}\n!/set(model=openrouter:gpt-4-turbo)"
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
def command_parser() -> CoreCommandProcessor:
    """Return a command processor backed by the shared command service builder."""

    from src.core.commands.parser import CommandParser

    class _SessionSvc:
        async def get_session(self, session_id: str) -> Session:
            return Session(session_id=session_id)

        async def update_session(self, session: Session) -> None:  # pragma: no cover
            return None

    command_service = build_new_command_service(
        session_service=_SessionSvc(),
        command_parser=CommandParser(),
    )

    import src.core.commands.handlers  # noqa: F401  Ensure handlers are registered

    class _NormalizingProcessor(CoreCommandProcessor):
        async def process_messages(  # type: ignore[override]
            self,
            messages: list[ChatMessage | MultimodalMessage],
            session_id: str,
            context: Any = None,
        ) -> ProcessedResult:
            normalized: list[ChatMessage] = []
            for message in messages:
                if isinstance(message, ChatMessage):
                    normalized.append(message)
                    continue
                text = (
                    message.get_text_content()
                    if hasattr(message, "get_text_content")
                    else ""
                )
                normalized.append(
                    ChatMessage(role=getattr(message, "role", "user"), content=text)
                )
            return await super().process_messages(normalized, session_id, context)

    processor = _NormalizingProcessor(command_service)

    import re as _re

    processor.command_pattern = _re.compile(r"!/[-\w]+(?:\([^)]*\))?")  # type: ignore[attr-defined]

    return processor


@pytest.fixture
async def process_command(
    command_parser: CoreCommandProcessor,
    test_session_id: str,
) -> Callable[[str], Coroutine[Any, Any, ProcessedResult]]:
    """Return a function to process a command."""

    async def _process_command(
        text: str,
    ) -> ProcessedResult:
        chat_message = ChatMessage(role="user", content=text)
        result = await command_parser.process_messages(
            [chat_message], session_id=test_session_id
        )
        return result

    return _process_command
