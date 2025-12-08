from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.session import Session, SessionState, SessionStateAdapter
from src.core.services.request_processor_service import RequestProcessor


class MockSessionManager:
    def __init__(self, session):
        self.session = session

    async def resolve_session_id(self, context):
        return self.session.session_id

    async def get_session(self, session_id):
        return self.session

    async def update_session_agent(self, session, agent):
        return session

    async def update_session_history(self, *args, **kwargs):
        pass

    async def record_command_in_session(self, *args, **kwargs):
        pass


@pytest.fixture
def session():
    state = SessionState(
        backend_config=BackendConfiguration(backend_type="mock", model="mock")
    )
    return Session(session_id="test-session", state=SessionStateAdapter(state))


@pytest.fixture
def request_processor(session):
    command_processor = MagicMock()
    command_processor.process_messages.return_value = ProcessedResult(
        command_executed=False, modified_messages=[], command_results=[]
    )

    session_manager = MockSessionManager(session)
    backend_request_manager = MagicMock()
    # Mock prepare_backend_request to return something or None
    backend_request_manager.prepare_backend_request = AsyncMock(
        return_value=ChatRequest(
            messages=[ChatMessage(role="user", content="mock")], model="mock"
        )
    )
    backend_request_manager.process_backend_request = AsyncMock(
        return_value=MagicMock()
    )

    response_manager = MagicMock()
    app_state = MagicMock()
    app_state.get_model_defaults.return_value = {}

    request_processor = RequestProcessor(
        command_processor=command_processor,
        session_manager=session_manager,
        backend_request_manager=backend_request_manager,
        response_manager=response_manager,
        app_state=app_state,
    )
    return request_processor


def create_context(session_state, original_request):
    app_state = MagicMock()
    return RequestContext(
        state=session_state,
        original_request=original_request,
        headers={},
        cookies={},
        app_state=app_state,
    )


@pytest.mark.asyncio
async def test_detect_client_os_windows_system_info(request_processor, session):
    request = ChatRequest(
        messages=[
            ChatMessage(
                role="user",
                content="<system-reminder>\nUser system info (win32 10.0.19045)\n</system-reminder>",
            ),
            ChatMessage(role="user", content="Hello"),
        ],
        model="mock",
    )
    context = create_context(session.state, request)

    await request_processor.process_request(context, request)

    assert session.state.client_os == "windows"


@pytest.mark.asyncio
async def test_detect_client_os_macos_system_info(request_processor, session):
    request = ChatRequest(
        messages=[
            ChatMessage(role="user", content="User system info (darwin 20.0.0)"),
        ],
        model="mock",
    )
    context = create_context(session.state, request)

    await request_processor.process_request(context, request)

    assert session.state.client_os == "macos"


@pytest.mark.asyncio
async def test_detect_client_os_linux_system_info(request_processor, session):
    request = ChatRequest(
        messages=[
            ChatMessage(role="user", content="User system info (linux 5.4.0)"),
        ],
        model="mock",
    )
    context = create_context(session.state, request)

    await request_processor.process_request(context, request)

    assert session.state.client_os == "linux"


@pytest.mark.asyncio
async def test_detect_client_os_windows_path(request_processor, session):
    request = ChatRequest(
        messages=[
            ChatMessage(role="user", content="I opened C:\\Users\\Name\\file.txt"),
        ],
        model="mock",
    )
    context = create_context(session.state, request)

    await request_processor.process_request(context, request)

    assert session.state.client_os == "windows"


@pytest.mark.asyncio
async def test_detect_client_os_no_detection(request_processor, session):
    request = ChatRequest(
        messages=[
            ChatMessage(role="user", content="Hello world"),
        ],
        model="mock",
    )
    context = create_context(session.state, request)

    await request_processor.process_request(context, request)

    assert session.state.client_os is None


@pytest.mark.asyncio
async def test_detect_client_os_preserves_existing(request_processor, session):
    # Set existing OS
    session.state = session.state.with_client_os("linux")

    # Request with Windows info
    request = ChatRequest(
        messages=[
            ChatMessage(role="user", content="User system info (win32 10.0.19045)"),
        ],
        model="mock",
    )
    context = create_context(session.state, request)

    await request_processor.process_request(context, request)

    # Should remain linux
    assert session.state.client_os == "linux"
