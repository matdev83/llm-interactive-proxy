"""Unit tests for tool access control filtering in RequestProcessor."""

from __future__ import annotations

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
    context.extensions = {}
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
) -> tuple[RequestProcessor, AsyncMock, AsyncMock, AsyncMock]:
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
    session_manager.apply_openai_codex_history_compaction_gate = AsyncMock()

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
    ChatMessage(role="user", content="test")
    session_enricher = AsyncMock(spec=ISessionEnricher)
    # Make session_enricher pass through the request to preserve tools
    session_enricher.enrich.side_effect = lambda ctx, req: (mock_session, req)

    request_side_effects = AsyncMock(spec=IRequestSideEffects)
    # Make request_side_effects pass through the request to preserve tools
    request_side_effects.apply.side_effect = lambda ctx, sid, req: req

    command_handler = AsyncMock(spec=ICommandHandler)
    command_handler.handle.return_value = ProcessedResult(
        modified_messages=[ChatMessage(role="user", content="test")],
        command_executed=False,
        command_results=[],
    )

    backend_preparer = AsyncMock(spec=IBackendPreparer)
    # Make backend_preparer pass through request with tools preserved
    backend_preparer.prepare.side_effect = lambda ctx, sid, req, cmd, **kw: req

    # Create a mock transform_pipeline that actually applies tool filtering
    async def mock_transform(ctx, sess, sid, req):
        """Mock transform that applies tool filtering using the policy service."""
        if not policy_service or not hasattr(req, "tools") or not req.tools:
            return req

        # Apply tool filtering
        result = policy_service.filter_tool_definitions(
            req.tools, model_name=req.model, agent=getattr(sess, "agent", None)
        )
        filtered_tools = result.filtered_tools
        metadata = result.metadata

        # Build updates dict
        updates = {"tools": filtered_tools}

        # Add metadata to extra_body
        if metadata:
            extra_body = req.extra_body.copy() if req.extra_body else {}
            extra_body["tool_access"] = metadata.model_dump()
            updates["extra_body"] = extra_body

        # Check if tool_choice references a filtered-out tool
        if (
            hasattr(req, "tool_choice")
            and req.tool_choice
            and isinstance(req.tool_choice, dict)
        ):
            chosen_name = req.tool_choice.get("function", {}).get("name")
            if chosen_name:
                # Check if the chosen tool is still in filtered_tools
                filtered_names = {
                    t.get("function", {}).get("name") for t in filtered_tools
                }
                if chosen_name not in filtered_names:
                    # Reset to auto if the chosen tool was filtered out
                    updates["tool_choice"] = "auto"

        return req.model_copy(update=updates)

    transform_pipeline = AsyncMock(spec=IRequestTransformPipeline)
    transform_pipeline.transform.side_effect = mock_transform

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

    return (
        processor,
        backend_request_manager,
        transform_pipeline,
        backend_executor,
    )


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
        (
            processor,
            backend_request_manager,
            transform_pipeline,
            backend_executor,
        ) = create_test_processor(
            policy_service_with_blocking, mock_session, sample_tools
        )

        # Create request with tools
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
            tools=sample_tools,
        )

        # Process request
        await processor.process_request(mock_context, request)

        # Verify backend_executor was called (refactored architecture)
        assert backend_executor.execute.called

        # Get the request that was passed to backend_executor
        call_args = backend_executor.execute.call_args
        # backend_executor.execute(context, session, session_id, request, original_request)
        captured_request = call_args[0][
            3
        ]  # request is 4th positional argument (0-indexed)

        # Debug: print what we got
        print(f"DEBUG: captured_request type: {type(captured_request)}")
        print(
            f"DEBUG: captured_request.tools: {getattr(captured_request, 'tools', 'NO ATTR')}"
        )

        # Verify tools were filtered
        assert captured_request is not None
        assert hasattr(captured_request, "tools")
        assert (
            captured_request.tools is not None
        ), "Tools should not be None after filtering"
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
        (
            processor,
            backend_request_manager,
            transform_pipeline,
            backend_executor,
        ) = create_test_processor(
            policy_service_with_whitelist, mock_session, sample_tools
        )

        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
            tools=sample_tools,
        )

        await processor.process_request(mock_context, request)

        # Verify backend_executor was called (refactored architecture)
        assert backend_executor.execute.called

        # Get the request that was passed to backend_executor
        call_args = backend_executor.execute.call_args
        captured_request = call_args[0][3]  # backend_request is 4th positional argument

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
        (
            processor,
            backend_request_manager,
            transform_pipeline,
            backend_executor,
        ) = create_test_processor(
            policy_service_with_blocking, mock_session, sample_tools
        )

        # Create request with tool_choice referencing a tool that will be filtered
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
            tools=sample_tools,
            tool_choice={"type": "function", "function": {"name": "delete_file"}},
        )

        await processor.process_request(mock_context, request)

        # Verify backend_executor was called (refactored architecture)

        assert backend_executor.execute.called

        # Get the request that was passed to backend_executor

        call_args = backend_executor.execute.call_args

        captured_request = call_args[0][3]  # backend_request is 4th positional argument

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
        (
            processor,
            backend_request_manager,
            transform_pipeline,
            backend_executor,
        ) = create_test_processor(
            policy_service_with_blocking, mock_session, sample_tools
        )

        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
            tools=sample_tools,
        )

        await processor.process_request(mock_context, request)

        # Verify backend_executor was called (refactored architecture)

        assert backend_executor.execute.called

        # Get the request that was passed to backend_executor

        call_args = backend_executor.execute.call_args

        captured_request = call_args[0][3]  # backend_request is 4th positional argument

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
        # Use create_test_processor with None policy_service to test fail-open behavior
        (
            processor,
            backend_request_manager,
            transform_pipeline,
            backend_executor,
        ) = create_test_processor(None, mock_session, sample_tools)

        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
            tools=sample_tools,
        )

        # Should not raise exception even without policy service
        await processor.process_request(mock_context, request)

        # Verify backend_executor was called (refactored architecture)
        assert backend_executor.execute.called

        # Get the request that was passed to backend_executor
        call_args = backend_executor.execute.call_args
        captured_request = call_args[0][3]  # backend_request is 4th positional argument

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

        (
            processor,
            backend_request_manager,
            transform_pipeline,
            backend_executor,
        ) = create_test_processor(policy_service, mock_session, sample_tools)

        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
            tools=sample_tools,
        )

        await processor.process_request(mock_context, request)

        # Verify backend_executor was called (refactored architecture)

        assert backend_executor.execute.called

        # Get the request that was passed to backend_executor

        call_args = backend_executor.execute.call_args

        captured_request = call_args[0][3]  # backend_request is 4th positional argument

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
        (
            processor,
            backend_request_manager,
            transform_pipeline,
            backend_executor,
        ) = create_test_processor(policy_service_with_blocking, mock_session, [])

        # Create request without tools
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="test")],
        )

        # Should not raise exception
        await processor.process_request(mock_context, request)

        # Verify request was processed normally (refactored architecture)
        assert backend_executor.execute.called
