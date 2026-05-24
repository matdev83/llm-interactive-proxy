"""
Tests for RequestTransformPipeline implementation.

Tests cover:
- Transformation ordering (redaction -> first-user append -> edit precision -> tool filtering)
- Fail-open behavior for each transformation
- Configuration-driven transformation gating
- Session and app_state interaction
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from src.core.domain.chat import (
    ChatMessage,
    ChatRequest,
    MessageContentPartText,
)
from src.core.domain.request_context import RequestContext
from src.core.domain.session import SessionState
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
    session.state.auto_append_first_prompt_applied = False
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
    the current execution order: redaction, optional first-user append, edit
    precision, then tool filtering.

    This test verifies transformations are called in the correct order.
    """
    pipeline = RequestTransformPipeline(app_state=mock_app_state)

    # Track order of transformation calls
    transformation_order = []

    # Mock each transformation method to track calls
    async def mock_redaction(ctx, session, session_id, request):
        transformation_order.append("redaction")
        return request

    async def mock_auto_append(ctx, session, session_id, request):
        transformation_order.append("auto_append_first_user")
        return request

    async def mock_precision(ctx, session, session_id, request):
        transformation_order.append("edit_precision")
        return request

    async def mock_filtering(ctx, session, session_id, request):
        transformation_order.append("tool_filtering")
        return request

    async def mock_auto_continue_removal(ctx, session, session_id, request):
        transformation_order.append("auto_continue_removal")
        return request

    async def mock_quality_verifier_injection(ctx, session, session_id, request):
        transformation_order.append("quality_verifier_steering")
        return request

    pipeline._apply_redaction = mock_redaction  # type: ignore
    pipeline._apply_auto_append_first_user_suffix = mock_auto_append  # type: ignore
    pipeline._apply_edit_precision = mock_precision  # type: ignore
    pipeline._apply_tool_filtering = mock_filtering  # type: ignore
    pipeline._apply_auto_continue_removal = mock_auto_continue_removal  # type: ignore
    pipeline._apply_quality_verifier_steering_injection = (  # type: ignore
        mock_quality_verifier_injection
    )

    # Execute transformation
    await pipeline.transform(
        request_context, basic_session, "test-session-id", basic_request
    )

    # Verify ordering
    assert transformation_order == [
        "redaction",
        "auto_append_first_user",
        "edit_precision",
        "tool_filtering",
        "auto_continue_removal",
        "quality_verifier_steering",
    ]


@pytest.mark.asyncio
async def test_quality_verifier_steering_injection_appends_system_message(
    mock_app_state: IApplicationState,
    request_context: RequestContext,
    basic_request: ChatRequest,
    basic_session: Mock,
) -> None:
    """Pending Quality Verifier steering should be injected as a system message."""
    pipeline = RequestTransformPipeline(app_state=mock_app_state)

    # Arrange: store pending steering in app_state settings
    pending_key = "quality_verifier_pending_steering_v1"

    def _get_setting(key: str, default: Any = None) -> Any:
        if key == pending_key:
            return {"qv-sess": {"message": "Do X", "created_at": 0.0}}
        return default

    cast(Any, mock_app_state).get_setting.side_effect = _get_setting

    # Ensure effective session key is used
    request_context.extensions["quality_verifier_effective_session_id"] = "qv-sess"

    result = await pipeline.transform(
        request_context,
        basic_session,
        "test-session-id",
        basic_request,
    )

    assert isinstance(result, ChatRequest)
    assert result.messages
    assert result.messages[-1].role == "system"
    assert "QUALITY VERIFIER" in str(result.messages[-1].content).upper()


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

    async def mock_auto_append(ctx, session, session_id, request):
        transformation_order.append("auto_append_first_user")
        return request

    pipeline._apply_redaction = failing_redaction  # type: ignore
    pipeline._apply_auto_append_first_user_suffix = mock_auto_append  # type: ignore
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
    assert transformation_order == [
        "auto_append_first_user",
        "edit_precision",
        "tool_filtering",
    ]


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

    async def mock_auto_append(ctx, session, session_id, request):
        transformation_order.append("auto_append_first_user")
        return request

    async def mock_filtering(ctx, session, session_id, request):
        transformation_order.append("tool_filtering")
        return request

    pipeline._apply_redaction = mock_redaction  # type: ignore
    pipeline._apply_auto_append_first_user_suffix = mock_auto_append  # type: ignore
    pipeline._apply_edit_precision = failing_precision  # type: ignore
    pipeline._apply_tool_filtering = mock_filtering  # type: ignore

    # Should not raise
    result = await pipeline.transform(
        request_context, basic_session, "test-session-id", basic_request
    )

    assert result is not None
    assert isinstance(result, ChatRequest)
    assert transformation_order == [
        "redaction",
        "auto_append_first_user",
        "tool_filtering",
    ]


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

    async def mock_auto_append(ctx, session, session_id, request):
        transformation_order.append("auto_append_first_user")
        return request

    async def mock_precision(ctx, session, session_id, request):
        transformation_order.append("edit_precision")
        return request

    pipeline._apply_redaction = mock_redaction  # type: ignore
    pipeline._apply_auto_append_first_user_suffix = mock_auto_append  # type: ignore
    pipeline._apply_edit_precision = mock_precision  # type: ignore
    pipeline._apply_tool_filtering = failing_filtering  # type: ignore

    # Should not raise
    result = await pipeline.transform(
        request_context, basic_session, "test-session-id", basic_request
    )

    assert result is not None
    assert isinstance(result, ChatRequest)
    assert transformation_order == [
        "redaction",
        "auto_append_first_user",
        "edit_precision",
    ]


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
    pipeline._apply_auto_append_first_user_suffix = failing_transform  # type: ignore
    pipeline._apply_edit_precision = failing_transform  # type: ignore
    pipeline._apply_tool_filtering = failing_transform  # type: ignore

    # Should not raise and should return original request
    result = await pipeline.transform(
        request_context, basic_session, "test-session-id", basic_request
    )

    assert result is not None
    assert result == basic_request


@pytest.mark.asyncio
async def test_auto_continue_removal_tags_exact_last_user_continue(
    mock_app_state: IApplicationState,
    request_context: RequestContext,
) -> None:
    from src.core.domain.non_forwardable import NonForwardableTagScope
    from src.core.interfaces.non_forwardable_interface import (
        INonForwardableMessageIdentityService,
        INonForwardableMessageRegistry,
    )

    mock_config = MagicMock()
    mock_config.session.auto_continue_removal_enabled = True

    registry = AsyncMock()
    identity_service = MagicMock()
    identity_service.compute_identity.return_value = "id-continue"

    def _get_setting(key: str, default: Any = None) -> Any:
        if key == "app_config":
            return mock_config
        return default

    def _get_service(service_type: Any) -> Any:
        name = getattr(service_type, "__name__", "")
        if name == INonForwardableMessageRegistry.__name__:
            return registry
        if name == INonForwardableMessageIdentityService.__name__:
            return identity_service
        return None

    cast(Any, mock_app_state).get_setting.side_effect = _get_setting
    cast(Any, mock_app_state).get_service.side_effect = _get_service

    req = ChatRequest(
        model="m",
        messages=[
            ChatMessage(role="system", content="sys"),
            ChatMessage(role="user", content="  CONTINUE  "),
        ],
    )

    pipeline = RequestTransformPipeline(app_state=mock_app_state)
    out = await pipeline._apply_auto_continue_removal(
        request_context, Mock(), "sid", req
    )

    assert out is req
    identity_service.compute_identity.assert_called_once_with(req.messages[-1])
    registry.tag_identities.assert_awaited_once_with(
        session_id="sid",
        identities=["id-continue"],
        scope=NonForwardableTagScope.NEVER_FORWARD,
        reason="auto_continue_removal",
    )


@pytest.mark.asyncio
async def test_auto_continue_removal_tags_exact_last_user_proceed(
    mock_app_state: IApplicationState,
    request_context: RequestContext,
) -> None:
    from src.core.domain.non_forwardable import NonForwardableTagScope
    from src.core.interfaces.non_forwardable_interface import (
        INonForwardableMessageIdentityService,
        INonForwardableMessageRegistry,
    )

    mock_config = MagicMock()
    mock_config.session.auto_continue_removal_enabled = True

    registry = AsyncMock()
    identity_service = MagicMock()
    identity_service.compute_identity.return_value = "id-proceed"

    def _get_setting(key: str, default: Any = None) -> Any:
        if key == "app_config":
            return mock_config
        return default

    def _get_service(service_type: Any) -> Any:
        name = getattr(service_type, "__name__", "")
        if name == INonForwardableMessageRegistry.__name__:
            return registry
        if name == INonForwardableMessageIdentityService.__name__:
            return identity_service
        return None

    cast(Any, mock_app_state).get_setting.side_effect = _get_setting
    cast(Any, mock_app_state).get_service.side_effect = _get_service

    req = ChatRequest(
        model="m",
        messages=[ChatMessage(role="user", content="proceed")],
    )

    pipeline = RequestTransformPipeline(app_state=mock_app_state)
    out = await pipeline._apply_auto_continue_removal(
        request_context, Mock(), "sid", req
    )

    assert out is req
    identity_service.compute_identity.assert_called_once_with(req.messages[-1])
    registry.tag_identities.assert_awaited_once_with(
        session_id="sid",
        identities=["id-proceed"],
        scope=NonForwardableTagScope.NEVER_FORWARD,
        reason="auto_continue_removal",
    )


@pytest.mark.asyncio
async def test_auto_continue_removal_does_not_tag_when_continue_not_last_user(
    mock_app_state: IApplicationState,
    request_context: RequestContext,
) -> None:
    from src.core.interfaces.non_forwardable_interface import (
        INonForwardableMessageIdentityService,
        INonForwardableMessageRegistry,
    )

    mock_config = MagicMock()
    mock_config.session.auto_continue_removal_enabled = True

    registry = AsyncMock()
    identity_service = MagicMock()

    def _get_setting(key: str, default: Any = None) -> Any:
        if key == "app_config":
            return mock_config
        return default

    def _get_service(service_type: Any) -> Any:
        name = getattr(service_type, "__name__", "")
        if name == INonForwardableMessageRegistry.__name__:
            return registry
        if name == INonForwardableMessageIdentityService.__name__:
            return identity_service
        return None

    cast(Any, mock_app_state).get_setting.side_effect = _get_setting
    cast(Any, mock_app_state).get_service.side_effect = _get_service

    req = ChatRequest(
        model="m",
        messages=[
            ChatMessage(role="user", content="continue"),
            ChatMessage(role="user", content="other"),
        ],
    )

    pipeline = RequestTransformPipeline(app_state=mock_app_state)
    out = await pipeline._apply_auto_continue_removal(
        request_context, Mock(), "sid", req
    )

    assert out is req
    identity_service.compute_identity.assert_not_called()
    registry.tag_identities.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_continue_removal_does_not_tag_when_message_has_extra_text(
    mock_app_state: IApplicationState,
    request_context: RequestContext,
) -> None:
    from src.core.interfaces.non_forwardable_interface import (
        INonForwardableMessageIdentityService,
        INonForwardableMessageRegistry,
    )

    mock_config = MagicMock()
    mock_config.session.auto_continue_removal_enabled = True

    registry = AsyncMock()
    identity_service = MagicMock()

    def _get_setting(key: str, default: Any = None) -> Any:
        if key == "app_config":
            return mock_config
        return default

    def _get_service(service_type: Any) -> Any:
        name = getattr(service_type, "__name__", "")
        if name == INonForwardableMessageRegistry.__name__:
            return registry
        if name == INonForwardableMessageIdentityService.__name__:
            return identity_service
        return None

    cast(Any, mock_app_state).get_setting.side_effect = _get_setting
    cast(Any, mock_app_state).get_service.side_effect = _get_service

    req = ChatRequest(
        model="m",
        messages=[ChatMessage(role="user", content="please continue")],
    )

    pipeline = RequestTransformPipeline(app_state=mock_app_state)
    out = await pipeline._apply_auto_continue_removal(
        request_context, Mock(), "sid", req
    )

    assert out is req
    identity_service.compute_identity.assert_not_called()
    registry.tag_identities.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_continue_removal_does_not_tag_when_disabled(
    mock_app_state: IApplicationState,
    request_context: RequestContext,
) -> None:
    from src.core.interfaces.non_forwardable_interface import (
        INonForwardableMessageIdentityService,
        INonForwardableMessageRegistry,
    )

    mock_config = MagicMock()
    mock_config.session.auto_continue_removal_enabled = False

    registry = AsyncMock()
    identity_service = MagicMock()

    def _get_setting(key: str, default: Any = None) -> Any:
        if key == "app_config":
            return mock_config
        return default

    def _get_service(service_type: Any) -> Any:
        name = getattr(service_type, "__name__", "")
        if name == INonForwardableMessageRegistry.__name__:
            return registry
        if name == INonForwardableMessageIdentityService.__name__:
            return identity_service
        return None

    cast(Any, mock_app_state).get_setting.side_effect = _get_setting
    cast(Any, mock_app_state).get_service.side_effect = _get_service

    req = ChatRequest(
        model="m",
        messages=[ChatMessage(role="user", content="continue")],
    )

    pipeline = RequestTransformPipeline(app_state=mock_app_state)
    out = await pipeline._apply_auto_continue_removal(
        request_context, Mock(), "sid", req
    )

    assert out is req
    identity_service.compute_identity.assert_not_called()
    registry.tag_identities.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_continue_removal_does_not_tag_when_last_message_not_user(
    mock_app_state: IApplicationState,
    request_context: RequestContext,
) -> None:
    from src.core.interfaces.non_forwardable_interface import (
        INonForwardableMessageIdentityService,
        INonForwardableMessageRegistry,
    )

    mock_config = MagicMock()
    mock_config.session.auto_continue_removal_enabled = True

    registry = AsyncMock()
    identity_service = MagicMock()

    def _get_setting(key: str, default: Any = None) -> Any:
        if key == "app_config":
            return mock_config
        return default

    def _get_service(service_type: Any) -> Any:
        name = getattr(service_type, "__name__", "")
        if name == INonForwardableMessageRegistry.__name__:
            return registry
        if name == INonForwardableMessageIdentityService.__name__:
            return identity_service
        return None

    cast(Any, mock_app_state).get_setting.side_effect = _get_setting
    cast(Any, mock_app_state).get_service.side_effect = _get_service

    req = ChatRequest(
        model="m",
        messages=[
            ChatMessage(role="user", content="continue"),
            ChatMessage(role="assistant", content="ok"),
        ],
    )

    pipeline = RequestTransformPipeline(app_state=mock_app_state)
    out = await pipeline._apply_auto_continue_removal(
        request_context, Mock(), "sid", req
    )

    assert out is req
    identity_service.compute_identity.assert_not_called()
    registry.tag_identities.assert_not_awaited()


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
    cast(Any, mock_app_state).get_setting.return_value = mock_config
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
    cast(Any, mock_app_state).get_setting.return_value = mock_config

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
async def test_redaction_does_not_pass_command_prefix(
    request_context: RequestContext,
    basic_request: ChatRequest,
) -> None:
    """
    Regression: Verify that command_prefix is NOT passed to RedactionMiddleware.

    Command filtering is no longer handled by RedactionMiddleware - it's handled
    by the non-forwardable message tagging system.
    """
    # Setup session
    session = Mock()
    session.agent = "test-agent"
    session.state = Mock()
    session.state.api_key_redaction_enabled = None  # Use config default

    mock_app_state = MagicMock(spec=IApplicationState)
    mock_config = MagicMock()
    mock_config.auth.redact_api_keys_in_prompts = True
    cast(Any, mock_app_state).get_setting.return_value = mock_config

    pipeline = RequestTransformPipeline(app_state=mock_app_state)

    # Mock RedactionMiddleware to verify command_prefix is NOT passed
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

            # Verify command_prefix is NOT in call kwargs
            call_kwargs = (
                mock_redaction_cls.call_args[1] if mock_redaction_cls.call_args else {}
            )
            assert "command_prefix" not in call_kwargs
            # Verify only api_keys is passed
            assert "api_keys" in call_kwargs


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
    cast(Any, mock_app_state).get_setting.return_value = mock_config
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


# ==============================================================================
# Test Requirement 5.1, 5.2: Copy-on-Write Immutability
# ==============================================================================


@pytest.mark.asyncio
async def test_transform_pipeline_preserves_original_request_instance(
    mock_app_state: IApplicationState,
    request_context: RequestContext,
    basic_request: ChatRequest,
    basic_session: Mock,
) -> None:
    """
    Requirement 5.1, 5.2: Contract mutations must use copy-on-write.

    This test verifies that the original request instance remains unchanged
    after transformation, and that mutations produce new instances.
    """
    pipeline = RequestTransformPipeline(app_state=mock_app_state)

    # Store original request ID for identity check
    original_id = id(basic_request)
    original_messages = basic_request.messages.copy()
    original_temperature = basic_request.temperature

    # Mock transformations to modify the request
    async def mock_redaction(ctx, session, session_id, request):
        # Modify temperature to verify copy-on-write
        return request.model_copy(update={"temperature": 0.5})

    async def mock_precision(ctx, session, session_id, request):
        # Modify temperature again
        return request.model_copy(update={"temperature": 0.3})

    async def mock_filtering(ctx, session, session_id, request):
        return request

    async def mock_auto_append(ctx, session, session_id, request):
        return request

    pipeline._apply_redaction = mock_redaction  # type: ignore
    pipeline._apply_auto_append_first_user_suffix = mock_auto_append  # type: ignore
    pipeline._apply_edit_precision = mock_precision  # type: ignore
    pipeline._apply_tool_filtering = mock_filtering  # type: ignore

    # Execute transformation
    result = await pipeline.transform(
        request_context, basic_session, "test-session-id", basic_request
    )

    # Verify original request instance is unchanged
    assert id(basic_request) == original_id, "Original request instance was mutated"
    assert (
        basic_request.temperature == original_temperature
    ), "Original request temperature was mutated"
    assert (
        basic_request.messages == original_messages
    ), "Original request messages were mutated"

    # Verify result is a new instance
    assert id(result) != original_id, "Result should be a new instance"
    assert result.temperature == 0.3, "Result should have modified temperature"


@pytest.mark.asyncio
async def test_edit_precision_preserves_original_request(
    request_context: RequestContext,
    basic_request: ChatRequest,
    basic_session: Mock,
) -> None:
    """
    Requirement 5.2: Edit precision tuning must preserve original request.
    """
    mock_app_state = MagicMock(spec=IApplicationState)
    mock_config = MagicMock()
    mock_config.edit_precision.enabled = True
    mock_config.edit_precision.temperature = 0.1
    cast(Any, mock_app_state).get_setting.return_value = mock_config

    pipeline = RequestTransformPipeline(app_state=mock_app_state)

    # Set original temperature
    original_request = basic_request.model_copy(update={"temperature": 0.8})
    original_id = id(original_request)
    original_temp = original_request.temperature

    # Mock edit precision to apply changes
    with patch(
        "src.core.services.edit_precision_middleware.EditPrecisionTuningMiddleware"
    ) as mock_middleware_cls:
        mock_instance = AsyncMock()
        # Return modified request
        modified_request = original_request.model_copy(update={"temperature": 0.1})
        mock_instance.process.return_value = modified_request
        mock_middleware_cls.return_value = mock_instance

        with patch(
            "src.core.config.edit_precision_temperatures.load_edit_precision_temperatures_config"
        ) as mock_load:
            mock_load.return_value = None

            result = await pipeline._apply_edit_precision(
                request_context, basic_session, "test-session-id", original_request
            )

            # Verify original is unchanged
            assert id(original_request) == original_id
            assert original_request.temperature == original_temp
            # Verify result is modified
            assert result.temperature == 0.1
            assert id(result) != original_id


@pytest.mark.asyncio
async def test_tool_filtering_preserves_original_request(
    request_context: RequestContext,
    basic_request: ChatRequest,
    basic_session: Mock,
) -> None:
    """
    Requirement 5.2: Tool filtering must preserve original request.
    """
    # Create request with tools
    request_with_tools = basic_request.model_copy(
        update={
            "tools": [
                {
                    "type": "function",
                    "function": {"name": "tool1", "description": "Test"},
                },
                {
                    "type": "function",
                    "function": {"name": "tool2", "description": "Test"},
                },
            ]
        }
    )
    original_id = id(request_with_tools)
    original_tools_count = len(request_with_tools.tools or [])

    mock_app_state = MagicMock(spec=IApplicationState)
    mock_policy_service = MagicMock()
    # Filter out one tool
    assert request_with_tools.tools is not None
    filtered_tools = [request_with_tools.tools[0]]
    from src.core.services.tool_access_policy_service import (
        ToolFilterMetadata,
        ToolFilterResult,
    )

    mock_policy_service.filter_tool_definitions.return_value = ToolFilterResult(
        filtered_tools=filtered_tools,
        metadata=ToolFilterMetadata(
            policy_applied="test",
            original_tool_count=len(request_with_tools.tools or []),
            filtered_tool_names=["tool2"],
            filtered_tool_count=1,
        ),
    )
    mock_app_state.get_service.return_value = mock_policy_service

    pipeline = RequestTransformPipeline(app_state=mock_app_state)

    result = await pipeline._apply_tool_filtering(
        request_context, basic_session, "test-session-id", request_with_tools
    )

    # Verify original is unchanged
    assert id(request_with_tools) == original_id
    assert len(request_with_tools.tools or []) == original_tools_count

    # Verify result is modified
    assert id(result) != original_id
    assert len(result.tools or []) == 1


@pytest.mark.asyncio
async def test_redaction_preserves_original_request(
    request_context: RequestContext,
    basic_request: ChatRequest,
    basic_session: Mock,
) -> None:
    """
    Requirement 5.2: Redaction must preserve original request instance.
    """
    mock_app_state = MagicMock(spec=IApplicationState)
    mock_config = MagicMock()
    mock_config.auth.redact_api_keys_in_prompts = True
    mock_config.command_prefix = "!/"
    cast(Any, mock_app_state).get_setting.return_value = mock_config
    mock_app_state.get_command_prefix.return_value = "!/"
    mock_app_state.get_disable_commands.return_value = False

    pipeline = RequestTransformPipeline(app_state=mock_app_state)

    # Create request with API key in content
    original_request = basic_request.model_copy(
        update={
            "messages": [
                ChatMessage(
                    role="user", content="My API key is FAKE_API_KEY_PLACEHOLDER_12345"
                )
            ]
        }
    )
    original_id = id(original_request)
    original_content = original_request.messages[0].content

    # Mock redaction to actually redact
    with patch(
        "src.core.services.redaction_middleware.RedactionMiddleware"
    ) as mock_redaction_cls:
        mock_instance = AsyncMock()
        # Return request with redacted content
        redacted_message = ChatMessage(
            role="user", content="My API key is sk-***REDACTED***"
        )
        redacted_request = original_request.model_copy(
            update={"messages": [redacted_message]}
        )
        mock_instance.process.return_value = redacted_request
        mock_redaction_cls.return_value = mock_instance

        with patch(
            "src.core.common.logging_utils.discover_api_keys_from_config_and_env"
        ) as mock_discover:
            mock_discover.return_value = ["FAKE_API_KEY_PLACEHOLDER_12345"]

            result = await pipeline._apply_redaction(
                request_context, basic_session, "test-session-id", original_request
            )

            # Verify original is unchanged
            assert id(original_request) == original_id
            assert original_request.messages[0].content == original_content
            # Verify result is modified
            assert result.messages[0].content != original_content
            assert id(result) != original_id


@pytest.mark.asyncio
async def test_auto_append_first_user_suffix_appends_to_first_user_message(
    mock_app_state: IApplicationState,
    request_context: RequestContext,
    basic_session: Mock,
) -> None:
    mock_config = MagicMock()
    mock_config.auto_append_first_prompt_text = "\n--tail--"
    cast(Any, mock_app_state).get_setting.return_value = mock_config

    session = Mock()
    session.state = SessionState()
    session.update_state = Mock()

    req = ChatRequest(
        model="m",
        messages=[
            ChatMessage(role="system", content="sys"),
            ChatMessage(role="user", content="hi"),
        ],
    )
    pipeline = RequestTransformPipeline(app_state=mock_app_state)
    out = await pipeline._apply_auto_append_first_user_suffix(
        request_context, session, "sid", req
    )
    assert out.messages[1].content == "hi\n--tail--"
    session.update_state.assert_called_once()


@pytest.mark.asyncio
async def test_auto_append_first_user_suffix_skips_when_already_applied(
    mock_app_state: IApplicationState,
    request_context: RequestContext,
    basic_session: Mock,
) -> None:
    mock_config = MagicMock()
    mock_config.auto_append_first_prompt_text = "\n--tail--"
    cast(Any, mock_app_state).get_setting.return_value = mock_config

    session = Mock()
    session.state = SessionState().with_auto_append_first_prompt_applied(True)
    session.update_state = Mock()

    req = ChatRequest(
        model="m",
        messages=[ChatMessage(role="user", content="hi")],
    )
    pipeline = RequestTransformPipeline(app_state=mock_app_state)
    out = await pipeline._apply_auto_append_first_user_suffix(
        request_context, session, "sid", req
    )
    assert out.messages[0].content == "hi"
    session.update_state.assert_not_called()


@pytest.mark.asyncio
async def test_auto_append_first_user_suffix_skips_auxiliary_request(
    mock_app_state: IApplicationState,
    request_context: RequestContext,
    basic_session: Mock,
) -> None:
    mock_config = MagicMock()
    mock_config.auto_append_first_prompt_text = "\n--tail--"
    cast(Any, mock_app_state).get_setting.return_value = mock_config

    session = Mock()
    session.state = SessionState()
    session.update_state = Mock()

    request_context.extensions["auxiliary_request"] = True

    req = ChatRequest(
        model="m",
        messages=[ChatMessage(role="user", content="hi")],
    )
    pipeline = RequestTransformPipeline(app_state=mock_app_state)
    out = await pipeline._apply_auto_append_first_user_suffix(
        request_context, session, "sid", req
    )
    assert out.messages[0].content == "hi"
    session.update_state.assert_not_called()


@pytest.mark.asyncio
async def test_auto_append_first_user_suffix_multimodal_list(
    mock_app_state: IApplicationState,
    request_context: RequestContext,
) -> None:
    mock_config = MagicMock()
    mock_config.auto_append_first_prompt_text = " END"
    cast(Any, mock_app_state).get_setting.return_value = mock_config

    session = Mock()
    session.state = SessionState()
    session.update_state = Mock()

    req = ChatRequest(
        model="m",
        messages=[
            ChatMessage(
                role="user",
                content=[MessageContentPartText(text="part1")],
            )
        ],
    )
    pipeline = RequestTransformPipeline(app_state=mock_app_state)
    out = await pipeline._apply_auto_append_first_user_suffix(
        request_context, session, "sid", req
    )
    parts = out.messages[0].content
    assert isinstance(parts, list)
    assert isinstance(parts[0], MessageContentPartText)
    assert parts[0].text == "part1\nEND"
