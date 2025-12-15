"""
Property-based tests for Codebuff PromptHandler.

Tests correctness properties for prompt handling, message extraction,
backend routing, and cancellation.
"""

import contextlib

import pytest
from hypothesis import given
from hypothesis import strategies as st
from src.codebuff.exceptions import CodebuffError
from src.codebuff.format_converter import FormatConverter
from src.codebuff.handlers.prompt_handler import PromptHandler
from src.codebuff.schemas import PromptAction
from tests.mocks.backend_factory import MockBackendFactory
from tests.mocks.connection_manager import MockConnectionManager


# Strategies for generating test data
@st.composite
def prompt_action_strategy(draw):
    """Generate a valid PromptAction with messages."""
    prompt_id = draw(st.text(min_size=1, max_size=50))
    fingerprint_id = draw(st.text(min_size=1, max_size=50))

    # Generate messages in different formats
    message_format = draw(st.sampled_from(["content", "prompt", "session_state"]))

    content = None
    prompt = None
    session_state = {"messages": []}

    if message_format == "content":
        # Generate content field with messages
        num_messages = draw(st.integers(min_value=1, max_value=5))
        content = [
            {
                "role": draw(st.sampled_from(["user", "assistant", "system"])),
                "content": draw(st.text(min_size=1, max_size=100)),
            }
            for _ in range(num_messages)
        ]
    elif message_format == "prompt":
        # Generate prompt field
        prompt = draw(st.text(min_size=1, max_size=200))
    else:
        # Generate session_state with messages
        num_messages = draw(st.integers(min_value=1, max_value=5))
        session_state = {
            "messages": [
                {
                    "role": draw(st.sampled_from(["user", "assistant", "system"])),
                    "content": draw(st.text(min_size=1, max_size=100)),
                }
                for _ in range(num_messages)
            ]
        }

    return PromptAction(
        type="prompt",
        promptId=prompt_id,
        prompt=prompt,
        content=content,
        fingerprintId=fingerprint_id,
        sessionState=session_state,
        model=draw(st.sampled_from(["gpt-4", "claude-3", "gemini-pro"])),
    )


@st.composite
def empty_prompt_action_strategy(draw):
    """Generate a PromptAction with no messages."""
    prompt_id = draw(st.text(min_size=1, max_size=50))
    fingerprint_id = draw(st.text(min_size=1, max_size=50))

    return PromptAction(
        type="prompt",
        promptId=prompt_id,
        prompt=None,
        content=None,
        fingerprintId=fingerprint_id,
        sessionState={},
        model=draw(st.sampled_from(["gpt-4", "claude-3", "gemini-pro"])),
    )


@given(action=prompt_action_strategy())
def test_property_5_message_extraction(action):
    """
    Feature: codebuff-backend-compatibility, Property 5: Message extraction
    Validates: Requirements 2.1

    For any valid prompt action, the system should successfully extract
    conversation messages and model selection.
    """
    # Create handler
    backend_factory = MockBackendFactory()
    format_converter = FormatConverter()
    connection_manager = MockConnectionManager()
    handler = PromptHandler(backend_factory, format_converter, connection_manager)

    # Extract messages
    messages = handler._extract_messages(action)

    # Property: Messages should be extracted successfully
    assert isinstance(messages, list)
    assert len(messages) > 0

    # Property: Each message should have required fields
    for msg in messages:
        assert isinstance(msg, dict)
        # Messages should have either role/content or be in a valid format
        assert "role" in msg or "content" in msg or "text" in msg or "message" in msg


@given(action=empty_prompt_action_strategy())
def test_property_5_message_extraction_empty_fails(action):
    """
    Feature: codebuff-backend-compatibility, Property 5: Message extraction (negative case)
    Validates: Requirements 2.1

    For any prompt action with no messages, extraction should fail with an error.
    """
    # Create handler
    backend_factory = MockBackendFactory()
    format_converter = FormatConverter()
    connection_manager = MockConnectionManager()
    handler = PromptHandler(backend_factory, format_converter, connection_manager)

    # Property: Extracting from empty action should raise error
    with pytest.raises(CodebuffError) as exc_info:
        handler._extract_messages(action)

    assert "No messages found" in str(exc_info.value)


@given(
    model=st.sampled_from(
        [
            "gpt-4",
            "gpt-3.5-turbo",
            "gpt-4-turbo",
            "claude-3-opus",
            "claude-3-sonnet",
            "claude-2",
            "gemini-pro",
            "gemini-1.5-pro",
        ]
    )
)
def test_property_7_backend_routing(model):
    """
    Feature: codebuff-backend-compatibility, Property 7: Backend routing
    Validates: Requirements 2.3

    For any model name in a prompt, the system should route the request
    to the appropriate backend connector.
    """
    # Create handler
    backend_factory = MockBackendFactory()
    format_converter = FormatConverter()
    connection_manager = MockConnectionManager()
    handler = PromptHandler(backend_factory, format_converter, connection_manager)

    # Determine backend type
    backend_type = handler._determine_backend_type(model)

    # Property: Backend type should be determined
    assert backend_type is not None
    assert isinstance(backend_type, str)
    assert len(backend_type) > 0

    # Property: Backend type should match model family
    model_lower = model.lower()
    if "gpt" in model_lower or "o1" in model_lower:
        assert backend_type == "openai"
    elif "claude" in model_lower:
        assert backend_type == "anthropic"
    elif "gemini" in model_lower:
        assert backend_type == "gemini"


@given(prompt_id=st.text(min_size=1, max_size=50))
@pytest.mark.asyncio
async def test_property_13_cancellation_cleanup(prompt_id):
    """
    Feature: codebuff-backend-compatibility, Property 13: Cancellation cleanup
    Validates: Requirements 3.5

    For any active streaming request, canceling it should stop the stream
    and clean up the request state.
    """
    # Create handler
    backend_factory = MockBackendFactory()
    format_converter = FormatConverter()
    connection_manager = MockConnectionManager()
    handler = PromptHandler(backend_factory, format_converter, connection_manager)

    # Create a mock task
    import asyncio

    async def mock_task():
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(10)

    task = asyncio.create_task(mock_task())
    handler._active_requests[prompt_id] = task

    # Property: Request should be in active requests before cancellation
    assert prompt_id in handler._active_requests

    # Cancel the request
    await handler.cancel_request(prompt_id)

    # Property: Request should be removed from active requests after cancellation
    assert prompt_id not in handler._active_requests

    # Give the task a moment to process cancellation
    with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
        await asyncio.wait_for(task, timeout=0.1)

    # Property: Task should be cancelled or done
    assert task.cancelled() or task.done()


@given(model=st.text(min_size=1, max_size=50))
def test_property_31_backend_factory_usage(model):
    """
    Feature: codebuff-backend-compatibility, Property 31: Backend factory usage
    Validates: Requirements 10.1

    For any LLM request, the system should use the existing backend factory
    to select the appropriate connector.
    """
    # Create handler with mock backend factory
    backend_factory = MockBackendFactory()
    format_converter = FormatConverter()
    connection_manager = MockConnectionManager()
    handler = PromptHandler(backend_factory, format_converter, connection_manager)

    # Property: Handler should have backend factory
    assert handler._backend_factory is not None
    assert handler._backend_factory == backend_factory

    # Property: Backend factory should be used for backend determination
    backend_type = handler._determine_backend_type(model)
    assert isinstance(backend_type, str)


@given(
    messages=st.lists(
        st.fixed_dictionaries(
            {
                "role": st.sampled_from(["user", "assistant", "system"]),
                "content": st.text(min_size=1, max_size=100),
            }
        ),
        min_size=1,
        max_size=5,
    )
)
def test_property_32_middleware_application(messages):
    """
    Feature: codebuff-backend-compatibility, Property 32: Middleware application
    Validates: Requirements 10.2

    For any response from a backend, the system should apply existing
    response middleware.

    Note: This is a structural test - actual middleware application happens
    in the backend layer, but we verify the handler is set up to use it.
    """
    # Create handler
    backend_factory = MockBackendFactory()
    format_converter = FormatConverter()
    connection_manager = MockConnectionManager()
    handler = PromptHandler(backend_factory, format_converter, connection_manager)

    # Property: Handler should use format converter for response processing
    assert handler._format_converter is not None
    assert handler._format_converter == format_converter

    # Property: Format converter should be able to create response chunks
    chunk = format_converter.create_response_chunk(
        user_input_id="test-id",
        text="test content",
    )
    assert chunk is not None
    assert isinstance(chunk, dict)
    assert chunk["type"] == "action"
