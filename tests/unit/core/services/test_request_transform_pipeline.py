"""
Tests for RequestTransformPipeline implementation.

Tests cover:
- Transformation ordering (redaction -> edit precision -> tool filtering)
- Fail-open behavior for each transformation
- Configuration-driven transformation gating
- Session and app_state interaction
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.services.request_transform_pipeline import RequestTransformPipeline


@pytest.fixture
def mock_app_state() -> IApplicationState:
    """Create a mock application state."""
    mock = MagicMock(spec=IApplicationState)

    # Default: no special configuration
    mock.get_setting.return_value = None
    mock.get_service.return_value = None

    return mock


@pytest.fixture
def request_context(mock_app_state: IApplicationState) -> RequestContext:
    """Create a basic request context."""
    return RequestContext(
        headers={},
        cookies={},
        state=MagicMock(),
        app_state=mock_app_state,
        client_host="127.0.0.1",
        original_request=None,
    )


@pytest.fixture
def basic_request() -> ChatRequest:
    """Create a basic chat request."""
    return ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
    )


@pytest.fixture
def basic_session() -> Mock:
    """Create a basic session mock."""
    session = Mock()
    session.agent = "test-agent"
    session.state = Mock()
    session.state.redact_api_keys_in_prompts_override = None
    return session


# ==============================================================================
# Test Requirement 9.7, 9.8: Transformation Ordering
# ==============================================================================


@pytest.mark.asyncio
async def test_transform_pipeline_preserves_ordering(
    mock_app_state: IApplicationState,
    request_context: RequestContext,
    basic_request: ChatRequest,
    basic_session: Mock,
) -> None:
    """
    Requirement 9.8: The request transformation pipeline shall preserve
    the current execution order: redaction, then edit precision, then tool filtering.

    This test verifies transformations are called in the correct order.
    """
    pipeline = RequestTransformPipeline(app_state=mock_app_state)

    # Track order of transformation calls
    transformation_order = []

    # Mock each transformation method to track calls
    async def mock_redaction(ctx, session, session_id, request):
        transformation_order.append("redaction")
        return request

    async def mock_precision(ctx, session, session_id, request):
        transformation_order.append("edit_precision")
        return request

    async def mock_filtering(ctx, session, session_id, request):
        transformation_order.append("tool_filtering")
        return request

    pipeline._apply_redaction = mock_redaction  # type: ignore
    pipeline._apply_edit_precision = mock_precision  # type: ignore
    pipeline._apply_tool_filtering = mock_filtering  # type: ignore

    # Execute transformation
    await pipeline.transform(
        request_context, basic_session, "test-session-id", basic_request
    )

    # Verify ordering
    assert transformation_order == ["redaction", "edit_precision", "tool_filtering"]


# ==============================================================================
# Test Requirement 9.7: Fail-Open Behavior
# ==============================================================================


@pytest.mark.asyncio
async def test_transform_pipeline_fail_open_on_redaction_error(
    mock_app_state: IApplicationState,
    request_context: RequestContext,
    basic_request: ChatRequest,
    basic_session: Mock,
) -> None:
    """
    Requirement 9.7: When any request transformation step fails unexpectedly,
    the Request Processor Service shall log and proceed without blocking
    request processing.

    This tests redaction failure handling.
    """
    pipeline = RequestTransformPipeline(app_state=mock_app_state)

    # Mock redaction to fail
    async def failing_redaction(ctx, session, session_id, request):
        raise RuntimeError("Redaction system error")

    # Track that other transformations still run
    transformation_order = []

    async def mock_precision(ctx, session, session_id, request):
        transformation_order.append("edit_precision")
        return request

    async def mock_filtering(ctx, session, session_id, request):
        transformation_order.append("tool_filtering")
        return request

    pipeline._apply_redaction = failing_redaction  # type: ignore
    pipeline._apply_edit_precision = mock_precision  # type: ignore
    pipeline._apply_tool_filtering = mock_filtering  # type: ignore

    # Should not raise, should proceed with remaining transformations
    result = await pipeline.transform(
        request_context, basic_session, "test-session-id", basic_request
    )

    # Verify we got a request back
    assert result is not None
    assert isinstance(result, ChatRequest)

    # Verify other transformations still ran
    assert transformation_order == ["edit_precision", "tool_filtering"]


@pytest.mark.asyncio
async def test_transform_pipeline_fail_open_on_precision_error(
    mock_app_state: IApplicationState,
    request_context: RequestContext,
    basic_request: ChatRequest,
    basic_session: Mock,
) -> None:
    """
    Requirement 9.7: Edit precision failure should not block the pipeline.
    """
    pipeline = RequestTransformPipeline(app_state=mock_app_state)

    # Mock edit precision to fail
    async def failing_precision(ctx, session, session_id, request):
        raise ValueError("Edit precision configuration error")

    # Track that other transformations still run
    transformation_order = []

    async def mock_redaction(ctx, session, session_id, request):
        transformation_order.append("redaction")
        return request

    async def mock_filtering(ctx, session, session_id, request):
        transformation_order.append("tool_filtering")
        return request

    pipeline._apply_redaction = mock_redaction  # type: ignore
    pipeline._apply_edit_precision = failing_precision  # type: ignore
    pipeline._apply_tool_filtering = mock_filtering  # type: ignore

    # Should not raise
    result = await pipeline.transform(
        request_context, basic_session, "test-session-id", basic_request
    )

    assert result is not None
    assert isinstance(result, ChatRequest)
    assert transformation_order == ["redaction", "tool_filtering"]


@pytest.mark.asyncio
async def test_transform_pipeline_fail_open_on_filtering_error(
    mock_app_state: IApplicationState,
    request_context: RequestContext,
    basic_request: ChatRequest,
    basic_session: Mock,
) -> None:
    """
    Requirement 9.7: Tool filtering failure should not block the pipeline.
    """
    pipeline = RequestTransformPipeline(app_state=mock_app_state)

    # Mock tool filtering to fail
    async def failing_filtering(ctx, session, session_id, request):
        raise AttributeError("Policy service unavailable")

    # Track that other transformations still run
    transformation_order = []

    async def mock_redaction(ctx, session, session_id, request):
        transformation_order.append("redaction")
        return request

    async def mock_precision(ctx, session, session_id, request):
        transformation_order.append("edit_precision")
        return request

    pipeline._apply_redaction = mock_redaction  # type: ignore
    pipeline._apply_edit_precision = mock_precision  # type: ignore
    pipeline._apply_tool_filtering = failing_filtering  # type: ignore

    # Should not raise
    result = await pipeline.transform(
        request_context, basic_session, "test-session-id", basic_request
    )

    assert result is not None
    assert isinstance(result, ChatRequest)
    assert transformation_order == ["redaction", "edit_precision"]


@pytest.mark.asyncio
async def test_transform_pipeline_all_transformations_fail(
    mock_app_state: IApplicationState,
    request_context: RequestContext,
    basic_request: ChatRequest,
    basic_session: Mock,
) -> None:
    """
    Edge case: Even if all transformations fail, the original request
    should be returned unchanged.
    """
    pipeline = RequestTransformPipeline(app_state=mock_app_state)

    # Mock all transformations to fail
    async def failing_transform(ctx, session, session_id, request):
        raise RuntimeError("Transformation failed")

    pipeline._apply_redaction = failing_transform  # type: ignore
    pipeline._apply_edit_precision = failing_transform  # type: ignore
    pipeline._apply_tool_filtering = failing_transform  # type: ignore

    # Should not raise and should return original request
    result = await pipeline.transform(
        request_context, basic_session, "test-session-id", basic_request
    )

    assert result is not None
    assert result == basic_request


# ==============================================================================
# Test Requirement 9.1, 9.2: Redaction Behavior
# ==============================================================================


@pytest.mark.asyncio
async def test_redaction_enabled_when_config_true(
    request_context: RequestContext,
    basic_request: ChatRequest,
    basic_session: Mock,
) -> None:
    """
    Requirement 9.1: When API key redaction is enabled by configuration,
    the Request Processor Service shall apply redaction to outbound requests.
    """
    # Setup app config with redaction enabled
    mock_app_state = MagicMock(spec=IApplicationState)
    mock_config = MagicMock()
    mock_config.auth.redact_api_keys_in_prompts = True
    mock_config.command_prefix = "!/"
    mock_app_state.get_setting.return_value = mock_config
    mock_app_state.get_command_prefix.return_value = "!/"
    mock_app_state.get_disable_commands.return_value = False

    pipeline = RequestTransformPipeline(app_state=mock_app_state)

    # Mock RedactionMiddleware to track if it was called
    with patch(
        "src.core.services.redaction_middleware.RedactionMiddleware"
    ) as mock_redaction_cls:
        mock_instance = AsyncMock()
        mock_instance.process.return_value = basic_request
        mock_redaction_cls.return_value = mock_instance

        with patch(
            "src.core.common.logging_utils.discover_api_keys_from_config_and_env"
        ) as mock_discover:
            mock_discover.return_value = ["test-key"]

            result = await pipeline._apply_redaction(
                request_context, basic_session, "test-session-id", basic_request
            )

            # Verify redaction was applied
            mock_redaction_cls.assert_called_once()
            mock_instance.process.assert_called_once()
            assert result == basic_request


@pytest.mark.asyncio
async def test_redaction_disabled_when_session_override_false(
    request_context: RequestContext,
    basic_request: ChatRequest,
) -> None:
    """
    Requirement 9.2: When API key redaction is disabled by session state,
    the Request Processor Service shall not instantiate or run redaction middleware.
    """
    # Setup session with redaction disabled
    session = Mock()
    session.agent = "test-agent"
    session.state = Mock()
    session.state.api_key_redaction_enabled = False

    mock_app_state = MagicMock(spec=IApplicationState)
    mock_config = MagicMock()
    mock_config.auth.redact_api_keys_in_prompts = True  # Config says enabled
    mock_app_state.get_setting.return_value = mock_config

    pipeline = RequestTransformPipeline(app_state=mock_app_state)

    # Mock RedactionMiddleware to track if it was called
    with patch(
        "src.core.services.redaction_middleware.RedactionMiddleware"
    ) as mock_redaction_cls:
        result = await pipeline._apply_redaction(
            request_context, session, "test-session-id", basic_request
        )

        # Verify redaction was NOT called (session override disabled it)
        mock_redaction_cls.assert_not_called()
        assert result == basic_request


@pytest.mark.asyncio
async def test_redaction_command_prefix_precedence(
    request_context: RequestContext,
    basic_request: ChatRequest,
) -> None:
    """
    Requirement 9.2: Command prefix resolution follows precedence:
    session > app_state > config
    """
    # Setup session with custom command prefix
    session = Mock()
    session.agent = "test-agent"
    session.state = Mock()
    session.state.api_key_redaction_enabled = None  # Use config default
    session.state.command_prefix_override = "$/session"  # Highest precedence

    mock_app_state = MagicMock(spec=IApplicationState)
    mock_config = MagicMock()
    mock_config.auth.redact_api_keys_in_prompts = True
    mock_config.command_prefix = "$/config"  # Lowest precedence
    mock_app_state.get_setting.return_value = mock_config
    mock_app_state.get_command_prefix.return_value = "$/appstate"  # Middle precedence
    mock_app_state.get_disable_commands.return_value = False

    pipeline = RequestTransformPipeline(app_state=mock_app_state)

    # Mock RedactionMiddleware to capture the command_prefix used
    with patch(
        "src.core.services.redaction_middleware.RedactionMiddleware"
    ) as mock_redaction_cls:
        mock_instance = AsyncMock()
        mock_instance.process.return_value = basic_request
        mock_redaction_cls.return_value = mock_instance

        with patch(
            "src.core.common.logging_utils.discover_api_keys_from_config_and_env"
        ) as mock_discover:
            mock_discover.return_value = ["test-key"]

            await pipeline._apply_redaction(
                request_context, session, "test-session-id", basic_request
            )

            # Verify session prefix was used (highest precedence)
            call_kwargs = mock_redaction_cls.call_args[1]
            assert call_kwargs["command_prefix"] == "$/session"


@pytest.mark.asyncio
async def test_redaction_fails_open_on_middleware_error(
    request_context: RequestContext,
    basic_request: ChatRequest,
    basic_session: Mock,
) -> None:
    """
    Requirement 9.7: When redaction middleware fails unexpectedly,
    the pipeline shall log and continue without blocking.
    """
    mock_app_state = MagicMock(spec=IApplicationState)
    mock_config = MagicMock()
    mock_config.auth.redact_api_keys_in_prompts = True
    mock_app_state.get_setting.return_value = mock_config
    mock_app_state.get_command_prefix.return_value = "!/"
    mock_app_state.get_disable_commands.return_value = False

    pipeline = RequestTransformPipeline(app_state=mock_app_state)

    # Mock RedactionMiddleware to fail
    with patch(
        "src.core.services.redaction_middleware.RedactionMiddleware"
    ) as mock_redaction_cls:
        mock_instance = AsyncMock()
        mock_instance.process.side_effect = RuntimeError("Redaction system error")
        mock_redaction_cls.return_value = mock_instance

        with patch(
            "src.core.common.logging_utils.discover_api_keys_from_config_and_env"
        ) as mock_discover:
            mock_discover.return_value = ["test-key"]

            # Should not raise, should return original request
            result = await pipeline._apply_redaction(
                request_context, basic_session, "test-session-id", basic_request
            )

            # Verify we got the original request back unchanged
            assert result == basic_request
