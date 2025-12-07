from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.config.app_config import AppConfig
from src.core.domain.request_context import RequestContext
from src.core.services.buffered_wire_capture_service import BufferedWireCapture


@pytest.mark.asyncio
async def test_buffered_wire_capture_isolation():
    """
    Test that BufferedWireCapture isolates state across sessions using separate buffers.
    """
    # 1. Setup
    config = MagicMock(spec=AppConfig)
    config.logging = MagicMock()
    config.logging.capture_file = "var/state/test_capture.jsonl"
    config.logging.capture_buffer_size = 100
    config.logging.capture_flush_interval = 60
    config.logging.capture_max_entries_per_flush = 100

    service = BufferedWireCapture(config)

    # Mock _flush_buffer to prevent flushing and verify buffer content
    service._flush_buffer = AsyncMock()

    # 2. Simulate Session A
    session_a_id = "session_A"
    context_a = RequestContext(
        headers={},
        cookies={},
        state=MagicMock(),
        app_state=MagicMock(),
        session_id=session_a_id,
    )
    payload_a = {"data": "secret_from_A"}

    await service.capture_outbound_request(
        context=context_a,
        session_id=session_a_id,
        backend="openai",
        model="gpt-4",
        key_name="test_key",
        request_payload=payload_a,
    )

    # 3. Simulate Session B
    session_b_id = "session_B"
    context_b = RequestContext(
        headers={},
        cookies={},
        state=MagicMock(),
        app_state=MagicMock(),
        session_id=session_b_id,
    )
    payload_b = {"data": "secret_from_B"}

    await service.capture_outbound_request(
        context=context_b,
        session_id=session_b_id,
        backend="openai",
        model="gpt-4",
        key_name="test_key",
        request_payload=payload_b,
    )

    # 4. Verify Isolation
    async with service._buffer_lock:
        # Verify we have separate buffers
        assert session_a_id in service._buffers, "Session A should have its own buffer"
        assert session_b_id in service._buffers, "Session B should have its own buffer"

        buffer_a = service._buffers[session_a_id]
        buffer_b = service._buffers[session_b_id]

        assert len(buffer_a) == 1
        assert buffer_a[0].session_id == session_a_id
        assert buffer_a[0].payload == payload_a

        assert len(buffer_b) == 1
        assert buffer_b[0].session_id == session_b_id
        assert buffer_b[0].payload == payload_b

        print("\n[Success] Buffers are isolated per session.")


@pytest.mark.asyncio
async def test_backend_service_isolation():
    """
    Test that BackendService creates separate backend instances for different sessions.
    """
    from src.core.interfaces.application_state_interface import IApplicationState
    from src.core.interfaces.rate_limiter_interface import IRateLimiter
    from src.core.interfaces.session_service_interface import ISessionService
    from src.core.services.backend_factory import BackendFactory
    from src.core.services.backend_service import BackendService

    # Mock dependencies
    factory = MagicMock(spec=BackendFactory)
    rate_limiter = MagicMock(spec=IRateLimiter)
    config = MagicMock(spec=AppConfig)
    session_service = MagicMock(spec=ISessionService)
    app_state = MagicMock(spec=IApplicationState)

    # Setup BackendService
    backend_service = BackendService(
        factory=factory,
        rate_limiter=rate_limiter,
        config=config,
        session_service=session_service,
        app_state=app_state,
    )

    # Mock factory to return different mock backends
    mock_backend_a = MagicMock()
    mock_backend_b = MagicMock()
    factory.ensure_backend.side_effect = [mock_backend_a, mock_backend_b]

    # 1. Request backend for Session A
    backend_a = await backend_service._get_or_create_backend(
        "openai", session_id="session_A"
    )

    # 2. Request backend for Session B
    backend_b = await backend_service._get_or_create_backend(
        "openai", session_id="session_B"
    )

    # 3. Verify they are DIFFERENT instances
    assert (
        backend_a is not backend_b
    ), "Backends should be different instances for different sessions"
    assert backend_a is mock_backend_a
    assert backend_b is mock_backend_b

    print("\n[Success] Backend instances are isolated per session.")
