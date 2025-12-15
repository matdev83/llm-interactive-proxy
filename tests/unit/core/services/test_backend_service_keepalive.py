from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.common.exceptions import BackendError
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.failure_strategy_interface import (
    FailureDecision,
    FailureHandlingConfig,
)
from src.core.services.backend_service import BackendService


@pytest.mark.asyncio
async def test_streaming_wait_and_retry_emits_keepalives():
    """Test that streaming requests emit keepalives during WAIT_AND_RETRY."""

    # Mock dependencies
    mock_factory = MagicMock()
    mock_factory.ensure_backend = AsyncMock()
    # If cache misses, factory returns the backend
    mock_factory.ensure_backend.return_value = (
        MagicMock()
    )  # replaced later or use side_effect
    mock_rate_limiter = MagicMock()
    mock_config = MagicMock()
    mock_session_service = MagicMock()
    mock_app_state = MagicMock()
    mock_routing_service = MagicMock()

    # Configure mock config using simple class to avoid MagicMock truthiness issues
    class MockBackends:
        static_route = None
        default_backend = "mock-backend"

        def get(self, key, default=None):
            return getattr(self, key, default)

    mock_config.get.return_value = {}
    mock_config.backends = MockBackends()

    # Configure mock routing service
    mock_routing_service.resolve_model_alias.return_value = ("mock-backend", "model")
    # resolve_backend_instance should return the string name of the backend, not the backend object
    mock_routing_service.resolve_backend_instance.return_value = "mock-backend"

    # Configure mock session service
    mock_session_service.get_session = AsyncMock(return_value=None)
    mock_session_service.update_session = AsyncMock()

    service = BackendService(
        factory=mock_factory,
        rate_limiter=mock_rate_limiter,
        config=mock_config,
        session_service=mock_session_service,
        app_state=mock_app_state,
        routing_service=mock_routing_service,
        failure_handling_strategy=MagicMock(),
    )

    # Configure failure handling on the same mock object
    mock_config.failure_handling = FailureHandlingConfig(keepalive_interval=0.1)

    # Ensure service uses this config
    service._config = mock_config

    # Mock _apply_failure_strategy
    service._apply_failure_strategy = AsyncMock()

    # Mock request
    mock_request = MagicMock()
    mock_request.stream = True
    mock_request.extra_body = {}
    mock_request.model_copy.return_value = mock_request
    mock_request.model = "test-model"

    # Mock Streaming Response for successful retry
    async def success_stream():
        yield "content chunk"

    success_response = StreamingResponseEnvelope(
        content=success_stream(), media_type="text/event-stream", headers={}
    )

    # Use MagicMock allowing sync methods by default, but make async methods explicitly AsyncMock
    mock_backend = MagicMock()
    mock_backend.chat_completions = AsyncMock()

    # Mock sync methods
    mock_backend.is_in_cooldown.return_value = False
    mock_backend.get_cooldown_remaining.return_value = 0.0
    mock_backend.get_retry_after_remaining.return_value = None

    mock_factory.ensure_backend.return_value = mock_backend
    # Mock chat_completions to raise BackendError then return success
    mock_backend.chat_completions.side_effect = [
        BackendError("Rate limited", status_code=429),  # 1st call
        success_response,  # 2nd call (retry)
    ]
    mock_backend.is_backend_functional.return_value = True

    service._backends = {"mock-backend": mock_backend}

    print(f"DEBUG: mock_backend type: {type(mock_backend)}")
    print(f"DEBUG: is_in_cooldown type: {type(mock_backend.is_in_cooldown)}")
    print(f"DEBUG: is_in_cooldown return: {mock_backend.is_in_cooldown()}")
    print(
        f"DEBUG: get_cooldown_remaining type: {type(mock_backend.get_cooldown_remaining)}"
    )
    print(
        f"DEBUG: get_cooldown_remaining return: {mock_backend.get_cooldown_remaining()}"
    )

    # Mock strategy to return WAIT_AND_RETRY
    service._apply_failure_strategy.return_value = (
        FailureDecision.WAIT_AND_RETRY,
        0.3,  # wait seconds
        None,  # next backend
    )

    # Call the service
    try:
        response = await service.call_completion(mock_request, stream=True)
    except BackendError as e:
        import traceback

        traceback.print_exc()
        print(f"BackendError caught: {e}")
        # If it has a cause, print it
        if e.__cause__:
            print(f"Caused by: {e.__cause__!r}")
        raise e

    assert isinstance(response, StreamingResponseEnvelope)

    # Consume the stream
    chunks = []
    headers = getattr(response, "headers", {})
    # Verify keep-alive headers
    assert headers.get("Connection") == "keep-alive"

    async for chunk in response.content:
        chunks.append(chunk)

    # Verification
    # 1. Should have keepalive chunks
    from src.core.interfaces.response_processor_interface import ProcessedResponse

    keepalives = [
        c
        for c in chunks
        if isinstance(c, ProcessedResponse) and bool(c.metadata.get("_keepalive"))
    ]
    assert len(keepalives) > 0, "Should emit at least one keepalive"

    # 2. Should have content chunk
    # 2. Should have content chunk
    content_chunks = []
    print("\nDEBUG: Received chunks:")
    for c in chunks:
        print(f"  - Type: {type(c)}, Value: {c}")
        if isinstance(c, ProcessedResponse):
            if c.content == "content chunk":
                content_chunks.append(c)
        elif c == "content chunk":
            content_chunks.append(c)
        elif isinstance(c, bytes) and b"content chunk" in c:
            # Maybe it got serialized?
            content_chunks.append(c)

    assert len(content_chunks) == 1

    # 3. Check retry call was made
    # Note: chat_completions is called twice:
    # 1. First call -> raises BackendError -> caught
    # 2. Second call (via recursion inside _wait_and_retry_stream) -> success
    assert mock_backend.chat_completions.call_count == 2
