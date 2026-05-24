"""Edit precision, hybrid reasoning, and pending-flag RequestProcessor tests."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.services.request_processor_service import RequestProcessor

from tests.unit.core.request_processor_test_support import (
    MockRequestContext,
    create_mock_request,
    create_request_processor_mocks,
)
from tests.unit.core.test_doubles import MockCommandProcessor, TestDataBuilder


@pytest.mark.asyncio
async def test_request_processor_applies_edit_precision_overrides_for_failed_edit_prompt() -> (
    None
):
    """Ensure edit-precision middleware lowers temperature/top_p for a single request when detection triggers."""
    # Arrange
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    # Mock the session manager to return our test session (no special agent)
    session = AsyncMock(id="test-session", agent="someagent")
    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = session

    # Provide AppConfig with edit_precision enabled and strict values

    from src.core.config.app_config import AppConfig, EditPrecisionConfig

    app_config = AppConfig(
        edit_precision=EditPrecisionConfig(
            enabled=True, temperature=0.05, min_top_p=0.2, override_top_p=True
        )
    )

    mock_app_state = MagicMock(spec=IApplicationState)
    mock_app_state.get_setting.return_value = app_config
    mock_app_state.get_command_prefix.return_value = "!/"

    # Create a request whose content includes a known failure phrase
    failure_text = "The SEARCH block ... does not match anything in the file"
    request_data = create_mock_request(
        stream=True, messages=[ChatMessage(role="user", content=failure_text)]
    )

    # Create required mocks
    (
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        _,
        backend_executor,
    ) = create_request_processor_mocks(
        session_manager,
        backend_request_manager,
        response_manager,
        command_processor,
        request_data,
    )
    # Setup session enricher to return the session
    session_enricher.enrich.return_value = (session, request_data)

    # Use real transform pipeline for edit precision tests
    from src.core.services.request_transform_pipeline import RequestTransformPipeline

    transform_pipeline = RequestTransformPipeline(app_state=mock_app_state)

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
        app_state=mock_app_state,
    )

    # No additional command modifications
    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    # Backend executor returns a dummy response
    response = TestDataBuilder.create_chat_response("OK")
    backend_executor.execute.return_value = response

    # Act
    await processor.process_request(MockRequestContext(), request_data)

    # Assert: backend executor was called with the transformed request (which applies edit precision)
    assert backend_executor.execute.called
    sent_request = backend_executor.execute.call_args[0][3]  # 4th arg is the request
    assert sent_request.temperature == pytest.approx(0.2)
    assert sent_request.top_p == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_request_processor_preserves_existing_low_temperature() -> None:
    """When a request is already deterministic, precision tuning must not raise the temperature."""
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    session = AsyncMock(id="test-session", agent="someagent")
    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = session

    from src.core.config.app_config import AppConfig, EditPrecisionConfig

    app_config = AppConfig(
        edit_precision=EditPrecisionConfig(
            enabled=True, temperature=0.05, min_top_p=0.2, override_top_p=True
        )
    )

    mock_app_state = MagicMock(spec=IApplicationState)
    mock_app_state.get_setting.return_value = app_config
    mock_app_state.get_command_prefix.return_value = "!/"

    failure_text = "The SEARCH block ... does not match anything in the file"
    request_data = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content=failure_text)],
        temperature=0.0,
        top_p=0.5,
        stream=True,
    )

    # Create required mocks
    (
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        _,
        backend_executor,
    ) = create_request_processor_mocks(
        session_manager,
        backend_request_manager,
        response_manager,
        command_processor,
        request_data,
    )
    # Setup session enricher to return the session
    session_enricher.enrich.return_value = (session, request_data)

    # Use real transform pipeline for edit precision tests
    from src.core.services.request_transform_pipeline import RequestTransformPipeline

    transform_pipeline = RequestTransformPipeline(app_state=mock_app_state)

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
        app_state=mock_app_state,
    )

    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    response = TestDataBuilder.create_chat_response("OK")
    backend_executor.execute.return_value = response

    await processor.process_request(MockRequestContext(), request_data)

    assert backend_executor.execute.called
    sent_request = backend_executor.execute.call_args[0][3]  # 4th arg is the request
    assert sent_request.temperature == pytest.approx(0.0)
    assert sent_request.top_p == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_request_processor_disables_hybrid_reasoning_after_flag() -> None:
    """Ensure hybrid reasoning is disabled on next turn when response middleware sets a flag."""

    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    session = AsyncMock(id="test-session", agent="someagent")
    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = session

    from src.core.config.app_config import AppConfig, EditPrecisionConfig

    app_config = AppConfig(
        edit_precision=EditPrecisionConfig(
            enabled=True,
            temperature=0.05,
            min_top_p=0.2,
            override_top_p=True,
        )
    )

    mock_app_state = MagicMock(spec=IApplicationState)
    app_state_store: dict[str, Any] = {
        "app_config": app_config,
        "edit_precision_pending": {},
        "edit_precision_hybrid_reasoning_disabled": {"test-session": True},
        "edit_precision_hybrid_reasoning_active": {"test-session": {"timestamp": 0.0}},
    }

    def get_setting_side_effect(key: str, default: Any | None = None) -> Any:
        return app_state_store.get(key, default)

    def set_setting_side_effect(key: str, value: Any) -> None:
        app_state_store[key] = value

    mock_app_state.get_setting.side_effect = get_setting_side_effect
    mock_app_state.set_setting.side_effect = set_setting_side_effect
    mock_app_state.get_command_prefix.return_value = "!/"

    request_data = ChatRequest(
        model="hybrid:[minimax:MiniMax-M2,qwen-oauth:qwen3-coder-plus]",
        messages=[ChatMessage(role="user", content="please continue")],
        temperature=0.7,
        top_p=0.9,
        extra_body={"hybrid_reasoning_probability": 0.6},
    )

    # Create required mocks
    (
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        _,
        backend_executor,
    ) = create_request_processor_mocks(
        session_manager,
        backend_request_manager,
        response_manager,
        command_processor,
        request_data,
    )
    # Setup session enricher to return the session
    session_enricher.enrich.return_value = (session, request_data)

    # Use real transform pipeline for edit precision tests
    from src.core.services.request_transform_pipeline import RequestTransformPipeline

    transform_pipeline = RequestTransformPipeline(app_state=mock_app_state)

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
        app_state=mock_app_state,
    )

    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    response = TestDataBuilder.create_chat_response("OK")
    backend_executor.execute.return_value = response

    await processor.process_request(MockRequestContext(), request_data)

    assert backend_executor.execute.called
    sent_request = backend_executor.execute.call_args[0][3]  # 4th arg is the request
    assert sent_request.extra_body.get("_temp_hybrid_reasoning_probability") == 0.0
    meta = sent_request.extra_body.get("_edit_precision_meta", {})
    assert meta.get("applied_hybrid_reasoning_probability") == 0.0
    mock_app_state.set_setting.assert_any_call(
        "edit_precision_hybrid_reasoning_disabled", {}
    )
    mock_app_state.set_setting.assert_any_call(
        "edit_precision_hybrid_reasoning_active", {}
    )


@pytest.mark.asyncio
async def test_request_processor_applies_edit_precision_temperature_override() -> None:
    """Ensure URI temperature is overridden on the next request after an edit failure."""

    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    session = AsyncMock(id="test-session", agent="roo")
    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = session

    from src.core.config.app_config import AppConfig, EditPrecisionConfig

    app_config = AppConfig(
        edit_precision=EditPrecisionConfig(
            enabled=True,
            temperature=0.0,
            min_top_p=0.2,
            override_top_p=True,
        )
    )

    mock_app_state = MagicMock(spec=IApplicationState)
    app_state_store: dict[str, Any] = {
        "app_config": app_config,
        "edit_precision_pending": {"test-session": 1},
        "edit_precision_hybrid_reasoning_disabled": {"test-session": True},
        "edit_precision_hybrid_reasoning_active": {"test-session": {"timestamp": 0.0}},
    }

    def get_setting_side_effect(key: str, default: Any | None = None) -> Any:
        return app_state_store.get(key, default)

    def set_setting_side_effect(key: str, value: Any) -> None:
        app_state_store[key] = value

    mock_app_state.get_setting.side_effect = get_setting_side_effect
    mock_app_state.set_setting.side_effect = set_setting_side_effect
    mock_app_state.get_command_prefix.return_value = "!/"

    request_data = ChatRequest(
        model="hybrid:[minimax:MiniMax-M2,qwen-oauth:qwen3-coder-plus?temperature=0.6]",
        messages=[ChatMessage(role="user", content="diff_error happened")],
        temperature=0.7,
        top_p=0.9,
        extra_body={"hybrid_reasoning_probability": 0.6},
    )

    # Create required mocks
    (
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        _,
        backend_executor,
    ) = create_request_processor_mocks(
        session_manager,
        backend_request_manager,
        response_manager,
        command_processor,
        request_data,
    )
    # Setup session enricher to return the session
    session_enricher.enrich.return_value = (session, request_data)

    # Use real transform pipeline for edit precision tests
    from src.core.services.request_transform_pipeline import RequestTransformPipeline

    transform_pipeline = RequestTransformPipeline(app_state=mock_app_state)

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
        app_state=mock_app_state,
    )

    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    response = TestDataBuilder.create_chat_response("OK")
    backend_executor.execute.return_value = response

    await processor.process_request(MockRequestContext(), request_data)

    assert backend_executor.execute.called
    sent_request = backend_executor.execute.call_args[0][3]  # 4th arg is the request
    assert sent_request.temperature == pytest.approx(0.0)
    assert sent_request.top_p == pytest.approx(0.2)
    assert app_state_store.get("edit_precision_hybrid_reasoning_disabled", {}) == {}


@pytest.mark.asyncio
async def test_request_processor_respects_exclude_agents_regex() -> None:
    """Ensure exclusion regex disables precision overrides for matching agents."""
    # Arrange
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    # Session agent matches exclusion
    session = AsyncMock(id="test-session", agent="cline")
    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = session
    # Ensure update_session_agent preserves the agent value
    session_manager.update_session_agent.return_value = session

    from src.core.config.app_config import AppConfig, EditPrecisionConfig

    app_config = AppConfig(
        edit_precision=EditPrecisionConfig(
            enabled=True,
            temperature=0.05,
            min_top_p=0.2,
            exclude_agents_regex=r"^(cline|roocode)$",
        )
    )

    mock_app_state = MagicMock(spec=IApplicationState)
    mock_app_state.get_setting.return_value = app_config
    mock_app_state.get_command_prefix.return_value = "!/"

    # Request includes failure phrase but should be excluded due to agent
    failure_text = "UnifiedDiffNoMatch: hunk failed to apply"
    # Seed with explicit starting values to ensure they remain unchanged
    request_data = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content=failure_text)],
        temperature=0.9,
        top_p=0.9,
        agent="cline",
    )

    # Create required mocks
    (
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        _,
        backend_executor,
    ) = create_request_processor_mocks(
        session_manager,
        backend_request_manager,
        response_manager,
        command_processor,
        request_data,
    )
    # Setup session enricher to return the session
    session_enricher.enrich.return_value = (session, request_data)

    # Use real transform pipeline for edit precision tests
    from src.core.services.request_transform_pipeline import RequestTransformPipeline

    transform_pipeline = RequestTransformPipeline(app_state=mock_app_state)

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
        app_state=mock_app_state,
    )

    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    response = TestDataBuilder.create_chat_response("OK")
    backend_executor.execute.return_value = response

    # Act
    await processor.process_request(MockRequestContext(), request_data)

    # Assert: params unchanged due to exclusion
    assert backend_executor.execute.called
    sent_request = backend_executor.execute.call_args[0][3]  # 4th arg is the request
    assert sent_request.temperature == pytest.approx(0.9)
    assert sent_request.top_p == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_request_processor_applies_overrides_when_pending_flag_set() -> None:
    """If response-side detection flagged a pending precision tune, the next request should be tuned even without prompt triggers."""
    # Arrange
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    # Mock session
    session = AsyncMock(id="test-session", agent="someagent")
    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = session

    from src.core.config.app_config import AppConfig, EditPrecisionConfig

    app_config = AppConfig(
        edit_precision=EditPrecisionConfig(
            enabled=True, temperature=0.2, min_top_p=0.4, override_top_p=True
        )
    )

    # Build a mock app_state that returns app_config and a pending flag map
    pending_map = {"test-session": 1}

    def _get_setting(name: str, default: object | None = None) -> object | None:
        if name == "app_config":
            return app_config
        if name == "edit_precision_pending":
            return pending_map
        return default

    mock_app_state = MagicMock(spec=IApplicationState)
    mock_app_state.get_setting.side_effect = _get_setting
    mock_app_state.get_command_prefix.return_value = "!/"

    # No failure phrase in message; tuning should still be applied due to pending flag
    request_data = create_mock_request(
        stream=False,
        messages=[ChatMessage(role="user", content="Proceed with next step")],
    )

    # Create required mocks
    (
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        _,
        backend_executor,
    ) = create_request_processor_mocks(
        session_manager,
        backend_request_manager,
        response_manager,
        command_processor,
        request_data,
    )
    # Setup session enricher to return the session
    session_enricher.enrich.return_value = (session, request_data)

    # Use real transform pipeline for edit precision tests
    from src.core.services.request_transform_pipeline import RequestTransformPipeline

    transform_pipeline = RequestTransformPipeline(app_state=mock_app_state)

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
        app_state=mock_app_state,
    )

    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    response = TestDataBuilder.create_chat_response("OK")
    backend_executor.execute.return_value = response

    # Act
    await processor.process_request(MockRequestContext(), request_data)

    # Assert request was tuned
    assert backend_executor.execute.called
    sent_request = backend_executor.execute.call_args[0][3]  # 4th arg is the request
    assert sent_request.temperature == pytest.approx(0.2)
    assert sent_request.top_p == pytest.approx(0.4)


@pytest.mark.asyncio
async def test_request_processor_clears_pending_entry_after_use() -> None:
    """Pending edit-precision flags should be removed once consumed."""
    command_processor = MockCommandProcessor()
    session_manager = AsyncMock()
    backend_request_manager = AsyncMock()
    response_manager = AsyncMock()

    session = AsyncMock(id="test-session", agent="someagent")
    session_manager.resolve_session_id.return_value = "test-session"
    session_manager.get_session.return_value = session

    from src.core.config.app_config import AppConfig, EditPrecisionConfig

    app_config = AppConfig(
        edit_precision=EditPrecisionConfig(
            enabled=True, temperature=0.2, min_top_p=0.4, override_top_p=True
        )
    )

    pending_map = {"test-session": 1}

    def _get_setting(name: str, default: object | None = None) -> object | None:
        if name == "app_config":
            return app_config
        if name == "edit_precision_pending":
            return pending_map
        return default

    mock_app_state = MagicMock(spec=IApplicationState)
    mock_app_state.get_setting.side_effect = _get_setting
    mock_app_state.get_command_prefix.return_value = "!/"

    request_data = create_mock_request(
        stream=False,
        messages=[ChatMessage(role="user", content="Proceed with next step")],
    )

    # Create required mocks
    (
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        _,
        backend_executor,
    ) = create_request_processor_mocks(
        session_manager,
        backend_request_manager,
        response_manager,
        command_processor,
        request_data,
    )
    # Setup session enricher to return the session
    session_enricher.enrich.return_value = (session, request_data)

    # Use real transform pipeline for edit precision tests
    from src.core.services.request_transform_pipeline import RequestTransformPipeline

    transform_pipeline = RequestTransformPipeline(app_state=mock_app_state)

    processor = RequestProcessor(
        command_processor,
        session_manager,
        backend_request_manager,
        response_manager,
        session_enricher,
        request_side_effects,
        command_handler,
        backend_preparer,
        transform_pipeline,
        backend_executor,
        app_state=mock_app_state,
    )

    command_processor.add_result(
        ProcessedResult(
            modified_messages=request_data.messages,
            command_executed=False,
            command_results=[],
        )
    )

    response = TestDataBuilder.create_chat_response("OK")
    backend_executor.execute.return_value = response

    await processor.process_request(MockRequestContext(), request_data)

    pending_updates = [
        call
        for call in mock_app_state.set_setting.call_args_list
        if call.args and call.args[0] == "edit_precision_pending"
    ]
    assert pending_updates, "expected pending map to be updated"
    updated_map = pending_updates[-1].args[1]
    assert isinstance(updated_map, dict)
    assert "test-session" not in updated_map
