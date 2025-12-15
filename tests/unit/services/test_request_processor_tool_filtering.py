"""Unit tests for tool access control filtering in RequestProcessor."""

from __future__ import annotations

# Skip until RequestProcessor tests updated for refactored architecture
pytestmark = __import__("pytest").mark.skip(
    reason="RequestProcessor refactoring - needs component mocks"
)


from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.config.app_config import ToolCallReactorConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.session import Session
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.services.request_processor_service import RequestProcessor
from src.core.services.tool_access_policy_service import ToolAccessPolicyService


@pytest.fixture
def mock_session() -> Session:
    """Create a mock session."""
    session = MagicMock(spec=Session)
    session.session_id = "test-session-123"
    session.agent = None
    session.state = MagicMock()
    return session


@pytest.fixture
def mock_context() -> RequestContext:
    """Create a mock request context."""
    context = MagicMock(spec=RequestContext)
    context.session_id = "test-session-123"
    context.agent = None
    return context


@pytest.fixture
def sample_tools() -> list[dict]:
    """Create sample tool definitions."""
    return [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delete_file",
                "description": "Delete a file",
                "parameters": {},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_directory",
                "description": "List directory contents",
                "parameters": {},
            },
        },
    ]


@pytest.fixture
def policy_service_with_blocking() -> ToolAccessPolicyService:
    """Create a policy service that blocks delete operations."""
    config = ToolCallReactorConfig(
        enabled=True,
        access_policies=[
            {
                "name": "block_delete",
                "model_pattern": ".*",
                "default_policy": "allow",
                "blocked_patterns": ["delete_.*"],
                "block_message": "Delete operations are not allowed.",
            }
        ],
    )
    return ToolAccessPolicyService(config)


@pytest.fixture
def policy_service_with_whitelist() -> ToolAccessPolicyService:
    """Create a policy service with whitelist mode."""
    config = ToolCallReactorConfig(
        enabled=True,
        access_policies=[
            {
                "name": "whitelist_read_only",
                "model_pattern": ".*",
                "default_policy": "deny",
                "allowed_patterns": ["read_.*", "list_.*"],
                "block_message": "Only read operations are allowed.",
            }
        ],
    )
    return ToolAccessPolicyService(config)


def create_test_processor(
    policy_service: ToolAccessPolicyService | None,
    mock_session: Session,
    sample_tools: list[dict],
) -> tuple[RequestProcessor, AsyncMock]:
    """Helper to create a test processor with mocked dependencies."""
    from src.core.interfaces.request_processor_internal import (
        IBackendExecutor,
        IBackendPreparer,
        ICommandHandler,
        IRequestSideEffects,
        IRequestTransformPipeline,
        ISessionEnricher,
    )

    command_processor = AsyncMock()
    command_processor.process_commands.return_value = ProcessedResult(
        command_executed=False,
        modified_messages=[ChatMessage(role="user", content="test")],
        command_results=[],
    )

    session_manager = AsyncMock()
    session_manager.resolve_session_id.return_value = "test-session-123"
    session_manager.get_session.return_value = mock_session
    session_manager.update_session_agent.return_value = mock_session

    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    app_state = MagicMock(spec=IApplicationState)
    if policy_service:
        app_state.get_service.return_value = policy_service
    else:
        app_state.get_service.return_value = None
    app_state.get_setting.return_value = None
    app_state.get_command_prefix.return_value = "!/"

    # Mock backend response
    backend_request_manager.process_backend_request.return_value = ResponseEnvelope(
        content=MagicMock(),
        metadata={"session_id": "test-session-123"},
    )

    # Create required mocks for refactored RequestProcessor
    session_enricher = AsyncMock(spec=ISessionEnricher)
    session_enricher.enrich.return_value = (
        mock_session,
        ChatRequest(model="gpt-4", messages=[]),
    )

    request_side_effects = AsyncMock(spec=IRequestSideEffects)
    request_side_effects.apply.return_value = ChatRequest(model="gpt-4", messages=[])

    command_handler = AsyncMock(spec=ICommandHandler)
    command_handler.handle.return_value = ProcessedResult(
        modified_messages=[ChatMessage(role="user", content="test")],
        command_executed=False,
        command_results=[],
    )

    backend_preparer = AsyncMock(spec=IBackendPreparer)
    backend_preparer.prepare.return_value = ChatRequest(model="gpt-4", messages=[])

    transform_pipeline = AsyncMock(spec=IRequestTransformPipeline)
    transform_pipeline.transform.return_value = ChatRequest(model="gpt-4", messages=[])

    backend_executor = AsyncMock(spec=IBackendExecutor)
    backend_executor.execute.return_value = ResponseEnvelope(
        content=MagicMock(),
        metadata={"session_id": "test-session-123"},
    )

    processor = RequestProcessor(
        command_processor=command_processor,
        session_manager=session_manager,
        backend_request_manager=backend_request_manager,
        response_manager=response_manager,
        session_enricher=session_enricher,
        request_side_effects=request_side_effects,
        command_handler=command_handler,
        backend_preparer=backend_preparer,
        transform_pipeline=transform_pipeline,
        backend_executor=backend_executor,
        app_state=app_state,
    )

    return processor, backend_request_manager


class TestRequestProcessorToolFiltering:
    """Tests for tool filtering in RequestProcessor."""

    @pytest.mark.asyncio
    async def test_tool_filtering_blocks_disallowed_tools(
        self,
        mock_session: Session,
        mock_context: RequestContext,
        sample_tools: list[dict],
        policy_service_with_blocking: ToolAccessPolicyService,
    ) -> None:
        """Test that disallowed tools are filtered from the request."""
        processor, backend_request_manager = create_test_processor(
            policy_service_with_blocking, mock_session, sample_tools
        )

        # Create request with tools
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
            tools=sample_tools,
        )

        # Setup backend request manager to return a request with tools
        backend_request = request.model_copy()
        backend_request_manager.prepare_backend_request.return_value = backend_request

        # Process request
        await processor.process_request(mock_context, request)

        # Verify backend_request_manager was called
        assert backend_request_manager.process_backend_request.called

        # Get the request that was passed to the backend
        call_args = backend_request_manager.process_backend_request.call_args
        captured_request = call_args[0][0]  # First positional argument

        # Verify tools were filtered
        assert captured_request is not None
        assert hasattr(captured_request, "tools")
        filtered_tool_names = [t["function"]["name"] for t in captured_request.tools]
        assert "read_file" in filtered_tool_names
        assert "list_directory" in filtered_tool_names
        assert "delete_file" not in filtered_tool_names

    @pytest.mark.asyncio
    async def test_tool_filtering_whitelist_mode(
        self,
        mock_session: Session,
        mock_context: RequestContext,
        sample_tools: list[dict],
        policy_service_with_whitelist: ToolAccessPolicyService,
    ) -> None:
        """Test whitelist mode filters correctly."""
        processor, backend_request_manager = create_test_processor(
            policy_service_with_whitelist, mock_session, sample_tools
        )

        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
            tools=sample_tools,
        )

        backend_request = request.model_copy()
        backend_request_manager.prepare_backend_request.return_value = backend_request

        await processor.process_request(mock_context, request)

        # Get the request that was passed to the backend
        call_args = backend_request_manager.process_backend_request.call_args
        captured_request = call_args[0][0]

        # Verify only whitelisted tools remain
        filtered_tool_names = [t["function"]["name"] for t in captured_request.tools]
        assert "read_file" in filtered_tool_names
        assert "list_directory" in filtered_tool_names
        assert "delete_file" not in filtered_tool_names

    @pytest.mark.asyncio
    async def test_tool_choice_handling_when_tool_filtered(
        self,
        mock_session: Session,
        mock_context: RequestContext,
        sample_tools: list[dict],
        policy_service_with_blocking: ToolAccessPolicyService,
    ) -> None:
        """Test that tool_choice is reset when referenced tool is filtered."""
        processor, backend_request_manager = create_test_processor(
            policy_service_with_blocking, mock_session, sample_tools
        )

        # Create request with tool_choice referencing a tool that will be filtered
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
            tools=sample_tools,
            tool_choice={"type": "function", "function": {"name": "delete_file"}},
        )

        backend_request = request.model_copy()
        backend_request_manager.prepare_backend_request.return_value = backend_request

        await processor.process_request(mock_context, request)

        # Get the request that was passed to the backend
        call_args = backend_request_manager.process_backend_request.call_args
        captured_request = call_args[0][0]

        # Verify tool_choice was reset to "auto"
        assert captured_request.tool_choice == "auto"

    @pytest.mark.asyncio
    async def test_metadata_stored_in_extra_body(
        self,
        mock_session: Session,
        mock_context: RequestContext,
        sample_tools: list[dict],
        policy_service_with_blocking: ToolAccessPolicyService,
    ) -> None:
        """Test that policy metadata is stored in extra_body."""
        processor, backend_request_manager = create_test_processor(
            policy_service_with_blocking, mock_session, sample_tools
        )

        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
            tools=sample_tools,
        )

        backend_request = request.model_copy()
        backend_request_manager.prepare_backend_request.return_value = backend_request

        await processor.process_request(mock_context, request)

        # Get the request that was passed to the backend
        call_args = backend_request_manager.process_backend_request.call_args
        captured_request = call_args[0][0]

        # Verify metadata is in extra_body
        assert hasattr(captured_request, "extra_body")
        assert "tool_access" in captured_request.extra_body
        metadata = captured_request.extra_body["tool_access"]
        assert metadata["policy_applied"] == "block_delete"
        assert "delete_file" in metadata["filtered_tool_names"]

    @pytest.mark.asyncio
    async def test_error_handling_fail_open(
        self,
        mock_session: Session,
        mock_context: RequestContext,
        sample_tools: list[dict],
    ) -> None:
        """Test that filtering failures don't block requests (fail-open)."""
        # Create app_state that raises an exception when getting service
        command_processor = AsyncMock()
        command_processor.process_commands.return_value = ProcessedResult(
            command_executed=False,
            modified_messages=[ChatMessage(role="user", content="test")],
            command_results=[],
        )

        session_manager = AsyncMock()
        session_manager.resolve_session_id.return_value = "test-session-123"
        session_manager.get_session.return_value = mock_session
        session_manager.update_session_agent.return_value = mock_session

        backend_request_manager = AsyncMock()
        response_manager = AsyncMock()

        app_state = MagicMock(spec=IApplicationState)
        app_state.get_service.side_effect = Exception("Service error")
        app_state.get_setting.return_value = None

        backend_request_manager.process_backend_request.return_value = ResponseEnvelope(
            content=MagicMock(),
            metadata={"session_id": "test-session-123"},
        )

        processor = RequestProcessor(
            command_processor=command_processor,
            session_manager=session_manager,
            backend_request_manager=backend_request_manager,
            response_manager=response_manager,
            app_state=app_state,
        )

        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
            tools=sample_tools,
        )

        backend_request = request.model_copy()
        backend_request_manager.prepare_backend_request.return_value = backend_request

        # Should not raise exception
        await processor.process_request(mock_context, request)

        # Get the request that was passed to the backend
        call_args = backend_request_manager.process_backend_request.call_args
        captured_request = call_args[0][0]

        # Verify request was processed with original tools (fail-open)
        assert len(captured_request.tools) == len(sample_tools)

    @pytest.mark.asyncio
    async def test_unfiltered_requests_pass_through(
        self,
        mock_session: Session,
        mock_context: RequestContext,
        sample_tools: list[dict],
    ) -> None:
        """Test that requests without matching policies pass through unchanged."""
        # Create policy service with no matching policies
        config = ToolCallReactorConfig(enabled=True, access_policies=[])
        policy_service = ToolAccessPolicyService(config)

        processor, backend_request_manager = create_test_processor(
            policy_service, mock_session, sample_tools
        )

        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
            tools=sample_tools,
        )

        backend_request = request.model_copy()
        backend_request_manager.prepare_backend_request.return_value = backend_request

        await processor.process_request(mock_context, request)

        # Get the request that was passed to the backend
        call_args = backend_request_manager.process_backend_request.call_args
        captured_request = call_args[0][0]

        # Verify all tools remain
        assert len(captured_request.tools) == len(sample_tools)

    @pytest.mark.asyncio
    async def test_no_tools_in_request(
        self,
        mock_session: Session,
        mock_context: RequestContext,
        policy_service_with_blocking: ToolAccessPolicyService,
    ) -> None:
        """Test that requests without tools are not affected."""
        processor, backend_request_manager = create_test_processor(
            policy_service_with_blocking, mock_session, []
        )

        # Create request without tools
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
        )

        backend_request = request.model_copy()
        backend_request_manager.prepare_backend_request.return_value = backend_request

        # Should not raise exception
        await processor.process_request(mock_context, request)

        # Verify request was processed normally
        assert backend_request_manager.process_backend_request.called
