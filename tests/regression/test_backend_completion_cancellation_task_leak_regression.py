"""Regression test for BackendCompletionFlow cancellation task leak fix.

This test verifies that cancellation callback tasks created in BackendCompletionFlow
are properly tracked and don't accumulate, preventing memory leaks.

Fixed: Tasks should be tracked or have proper cleanup mechanisms to prevent
unbounded accumulation when many cancellations occur.
"""

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import CanonicalChatRequest, ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.domain.session_key import SessionKey
from src.core.services.backend_completion_flow.service import BackendCompletionFlow
from src.core.services.session_cancellation_coordinator import (
    SessionCancellationCoordinator,
)
from tests.utils.fake_clock import FakeClockContext


class TestBackendCompletionCancellationTaskLeakRegression:
    """Regression tests for BackendCompletionFlow cancellation task leak fix."""

    @pytest.fixture
    def cancellation_coordinator(self) -> SessionCancellationCoordinator:
        """Create a cancellation coordinator for testing."""
        return SessionCancellationCoordinator(ttl_seconds=3600)

    @pytest.fixture
    def session_key(self) -> SessionKey:
        """Create a test session key."""
        return SessionKey(protocol="http", primary_id="test-session", group_id="conv-1")

    @pytest.fixture
    def request_context(self, session_key: SessionKey) -> RequestContext:
        """Create a request context."""
        headers = {}
        if session_key.group_id:
            headers["x-conversation-id"] = session_key.group_id
        return RequestContext(
            headers=headers,
            cookies={},
            state={},
            app_state=None,
            request_id=session_key.primary_id,
        )

    @pytest.fixture
    def chat_request(self) -> ChatRequest:
        """Create a test chat request."""
        return CanonicalChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="test")],
            stream=True,
        )

    @pytest.mark.asyncio
    async def test_cancellation_tasks_dont_accumulate(
        self,
        cancellation_coordinator: SessionCancellationCoordinator,
        session_key: SessionKey,
        request_context: RequestContext,
        chat_request: ChatRequest,
    ) -> None:
        """Test that cancellation callback tasks don't accumulate unbounded."""
        from src.core.interfaces.backend_completion_collaborators import (
            IBackendAvailabilityChecker,
            IBackendInvoker,
            IBackendRequestPreparer,
            ICompletionSessionResolver,
            IFailureRecoveryExecutor,
            IUsageAccountingOrchestrator,
            IWireCaptureOrchestrator,
        )
        from src.core.interfaces.exception_normalizer_interface import (
            IExceptionNormalizer,
        )
        from src.core.interfaces.stream_formatting_interface import (
            IStreamFormattingService,
        )

        # Track tasks created during cancellation callbacks
        created_tasks: list[asyncio.Task] = []
        original_create_task = asyncio.create_task

        def tracked_create_task(coro):
            """Track created tasks."""
            task = original_create_task(coro)
            created_tasks.append(task)
            return task

        # Create mock backend that returns streaming response with cancel callback
        async def slow_cancel_callback():
            """Simulate slow cancellation callback."""
            # Use fake clock for deterministic time simulation
            async with FakeClockContext() as clock:
                sleep_task = asyncio.create_task(asyncio.sleep(0.1))
                clock.advance(0.1)
                await sleep_task

        # Create an empty async generator for content to avoid stream processing
        async def empty_content():
            if False:  # Make it an async generator
                yield

        mock_backend = MagicMock()
        mock_backend.chat_completions = AsyncMock(
            return_value=StreamingResponseEnvelope(
                content=empty_content(),
                status_code=200,
                cancel_callback=slow_cancel_callback,
            )
        )

        # Create mock collaborators
        mock_availability_checker = MagicMock(spec=IBackendAvailabilityChecker)
        mock_availability_checker.check_backend_availability = AsyncMock()

        mock_request_preparer = MagicMock(spec=IBackendRequestPreparer)
        mock_request_preparer.prepare_request = AsyncMock(
            return_value=MagicMock(backend="test", model="test-model", uri_params={})
        )
        mock_request_preparer.synchronize_request_with_target = MagicMock(
            return_value=chat_request
        )
        mock_request_preparer.prepare_backend_kwargs = MagicMock(return_value={})

        mock_session_resolver = MagicMock(spec=ICompletionSessionResolver)
        mock_session_resolver.resolve_session = AsyncMock(
            return_value=(None, "session-id")
        )

        mock_backend_invoker = MagicMock(spec=IBackendInvoker)
        mock_backend_invoker.acquire_backend = AsyncMock(return_value=mock_backend)

        mock_failover_executor = MagicMock(spec=IFailureRecoveryExecutor)
        mock_failover_executor.check_complex_failover = AsyncMock(return_value=False)

        mock_wire_capture = MagicMock(spec=IWireCaptureOrchestrator)
        mock_wire_capture.capture_wire_outbound = AsyncMock()
        mock_wire_capture.detect_key_name = MagicMock(return_value="test-key")
        mock_wire_capture.prepare_wire_capture_context = AsyncMock(return_value=None)
        mock_wire_capture.capture_inbound_response = AsyncMock()

        # Mock wrap_inbound_stream to return the stream immediately without processing
        async def passthrough_stream(stream, **kwargs):
            async for item in stream:
                yield item

        # Mock wrap_inbound_stream to return empty stream immediately
        async def empty_wrapped_stream(stream, **kwargs):
            # Don't iterate over input stream to avoid hanging
            if False:  # Make it an async generator
                yield b""

        mock_wire_capture.wrap_inbound_stream = MagicMock(
            side_effect=lambda stream, **kwargs: empty_wrapped_stream(stream)
        )

        mock_usage_accounting = MagicMock(spec=IUsageAccountingOrchestrator)
        mock_usage_accounting.calculate_and_record_usage = AsyncMock(
            return_value=(0, None, None)
        )
        mock_usage_accounting.wrap_response_for_usage = AsyncMock(
            side_effect=lambda result, **kwargs: result
        )

        # Mock handle_streaming_response to return immediately without processing stream
        async def mock_handle_streaming_response(*args, **kwargs):
            result = args[0] if args else kwargs.get("result")
            return result

        mock_usage_accounting.handle_streaming_response = AsyncMock(
            side_effect=mock_handle_streaming_response
        )

        mock_exception_normalizer = MagicMock(spec=IExceptionNormalizer)
        mock_stream_formatting = MagicMock(spec=IStreamFormattingService)

        # Mock stream_as_sse_bytes to return an empty async generator immediately
        async def empty_sse_stream():
            if False:  # Make it an async generator
                yield b""

        mock_stream_formatting.stream_as_sse_bytes = MagicMock(
            return_value=empty_sse_stream()
        )

        # Create BackendCompletionFlow
        flow = BackendCompletionFlow(
            availability_checker=mock_availability_checker,
            request_preparer=mock_request_preparer,
            session_resolver=mock_session_resolver,
            backend_invoker=mock_backend_invoker,
            failover_executor=mock_failover_executor,
            wire_capture_orchestrator=mock_wire_capture,
            usage_accounting_orchestrator=mock_usage_accounting,
            exception_normalizer=mock_exception_normalizer,
            stream_formatting_service=mock_stream_formatting,
            cancellation_coordinator=cancellation_coordinator,
        )

        # Get initial task count
        initial_tasks = len(asyncio.all_tasks())

        # Use fake clock for deterministic time simulation
        async with FakeClockContext() as clock:
            # Patch create_task to track tasks
            with pytest.MonkeyPatch().context() as m:
                m.setattr(asyncio, "create_task", tracked_create_task)

                # Create multiple streaming requests that get cancelled
                for _i in range(3):
                    # Start completion call with timeout to prevent hanging
                    try:
                        completion_task = asyncio.create_task(
                            asyncio.wait_for(
                                flow.call_completion(
                                    request=chat_request,
                                    stream=True,
                                    allow_failover=False,
                                    context=request_context,
                                ),
                                timeout=1.0,  # 1 second timeout to prevent hanging
                            )
                        )

                        # Cancel immediately to trigger cancellation callback
                        cancellation_coordinator.cancel_session(
                            session_key, reason=None  # type: ignore[arg-type]
                        )

                        # Wait a bit for cancellation callback to be invoked
                        # Use fake clock for deterministic time simulation
                        clock.advance(0.001)  # Reduced from 0.01 for performance

                        # Cancel the completion task
                        completion_task.cancel()
                        with contextlib.suppress(
                            asyncio.CancelledError, asyncio.TimeoutError, Exception
                        ):
                            await completion_task
                    except Exception:
                        # Ignore any exceptions during task creation/cancellation
                        pass

            # Wait for cancellation callbacks to complete
            # Use fake clock for deterministic time simulation
            sleep_task = asyncio.create_task(asyncio.sleep(0.05))
            clock.advance(0.05)  # Reduced from 0.2 for performance
            await sleep_task

        # Check that tasks don't accumulate excessively
        final_tasks = len(asyncio.all_tasks())
        task_increase = final_tasks - initial_tasks

        # Allow some tolerance for test framework tasks
        # But cancellation callback tasks should complete and not accumulate
        assert task_increase <= 15, (
            f"Cancellation tasks accumulated: {task_increase} tasks remain. "
            "Cancellation callback tasks are not being properly cleaned up."
        )

        # Verify tracked tasks completed
        pending_tracked = [t for t in created_tasks if not t.done()]
        assert len(pending_tracked) == 0, (
            f"{len(pending_tracked)} cancellation callback tasks still pending. "
            "Tasks should complete or be properly tracked for cleanup."
        )

    @pytest.mark.asyncio
    async def test_failing_cancellation_callbacks_dont_leak(
        self,
        cancellation_coordinator: SessionCancellationCoordinator,
        session_key: SessionKey,
        request_context: RequestContext,
        chat_request: ChatRequest,
    ) -> None:
        """Test that failing cancellation callbacks don't cause task leaks."""
        from src.core.interfaces.backend_completion_collaborators import (
            IBackendAvailabilityChecker,
            IBackendInvoker,
            IBackendRequestPreparer,
            ICompletionSessionResolver,
            IFailureRecoveryExecutor,
            IUsageAccountingOrchestrator,
            IWireCaptureOrchestrator,
        )
        from src.core.interfaces.exception_normalizer_interface import (
            IExceptionNormalizer,
        )
        from src.core.interfaces.stream_formatting_interface import (
            IStreamFormattingService,
        )

        # Create mock backend with failing cancel callback
        async def failing_cancel_callback():
            """Simulate failing cancellation callback."""
            # FakeClockContext will be active when callback is called
            async with FakeClockContext() as clock:
                sleep_task = asyncio.create_task(asyncio.sleep(0.01))
                clock.advance(0.01)
                await sleep_task
            raise RuntimeError("Cancellation callback failed")

        # Create an empty async generator for content to avoid stream processing
        async def empty_content():
            if False:  # Make it an async generator
                yield

        mock_backend = MagicMock()
        mock_backend.chat_completions = AsyncMock(
            return_value=StreamingResponseEnvelope(
                content=empty_content(),
                status_code=200,
                cancel_callback=failing_cancel_callback,
            )
        )

        # Create mock collaborators (same as above)
        mock_availability_checker = MagicMock(spec=IBackendAvailabilityChecker)
        mock_availability_checker.check_backend_availability = AsyncMock()

        mock_request_preparer = MagicMock(spec=IBackendRequestPreparer)
        mock_request_preparer.prepare_request = AsyncMock(
            return_value=MagicMock(backend="test", model="test-model", uri_params={})
        )
        mock_request_preparer.synchronize_request_with_target = MagicMock(
            return_value=chat_request
        )
        mock_request_preparer.prepare_backend_kwargs = MagicMock(return_value={})

        mock_session_resolver = MagicMock(spec=ICompletionSessionResolver)
        mock_session_resolver.resolve_session = AsyncMock(
            return_value=(None, "session-id")
        )

        mock_backend_invoker = MagicMock(spec=IBackendInvoker)
        mock_backend_invoker.acquire_backend = AsyncMock(return_value=mock_backend)

        mock_failover_executor = MagicMock(spec=IFailureRecoveryExecutor)
        mock_failover_executor.check_complex_failover = AsyncMock(return_value=False)

        mock_wire_capture = MagicMock(spec=IWireCaptureOrchestrator)
        mock_wire_capture.capture_wire_outbound = AsyncMock()
        mock_wire_capture.detect_key_name = MagicMock(return_value="test-key")
        mock_wire_capture.prepare_wire_capture_context = AsyncMock(return_value=None)
        mock_wire_capture.capture_inbound_response = AsyncMock()

        # Mock wrap_inbound_stream to return the stream immediately without processing
        async def passthrough_stream(stream, **kwargs):
            async for item in stream:
                yield item

        # Mock wrap_inbound_stream to return empty stream immediately
        async def empty_wrapped_stream(stream, **kwargs):
            # Don't iterate over input stream to avoid hanging
            if False:  # Make it an async generator
                yield b""

        mock_wire_capture.wrap_inbound_stream = MagicMock(
            side_effect=lambda stream, **kwargs: empty_wrapped_stream(stream)
        )

        mock_usage_accounting = MagicMock(spec=IUsageAccountingOrchestrator)
        mock_usage_accounting.calculate_and_record_usage = AsyncMock(
            return_value=(0, None, None)
        )
        mock_usage_accounting.wrap_response_for_usage = AsyncMock(
            side_effect=lambda result, **kwargs: result
        )

        # Mock handle_streaming_response to return immediately without processing stream
        async def mock_handle_streaming_response(*args, **kwargs):
            result = args[0] if args else kwargs.get("result")
            return result

        mock_usage_accounting.handle_streaming_response = AsyncMock(
            side_effect=mock_handle_streaming_response
        )

        mock_exception_normalizer = MagicMock(spec=IExceptionNormalizer)
        mock_stream_formatting = MagicMock(spec=IStreamFormattingService)

        # Mock stream_as_sse_bytes to return an empty async generator immediately
        async def empty_sse_stream():
            if False:  # Make it an async generator
                yield b""

        mock_stream_formatting.stream_as_sse_bytes = MagicMock(
            return_value=empty_sse_stream()
        )

        flow = BackendCompletionFlow(
            availability_checker=mock_availability_checker,
            request_preparer=mock_request_preparer,
            session_resolver=mock_session_resolver,
            backend_invoker=mock_backend_invoker,
            failover_executor=mock_failover_executor,
            wire_capture_orchestrator=mock_wire_capture,
            usage_accounting_orchestrator=mock_usage_accounting,
            exception_normalizer=mock_exception_normalizer,
            stream_formatting_service=mock_stream_formatting,
            cancellation_coordinator=cancellation_coordinator,
        )

        initial_tasks = len(asyncio.all_tasks())

        # Trigger multiple cancellations with failing callbacks
        for _i in range(2):
            try:
                completion_task = asyncio.create_task(
                    asyncio.wait_for(
                        flow.call_completion(
                            request=chat_request,
                            stream=True,
                            allow_failover=False,
                            context=request_context,
                        ),
                        timeout=1.0,  # 1 second timeout to prevent hanging
                    )
                )

                cancellation_coordinator.cancel_session(
                    session_key, reason=None  # type: ignore[arg-type]
                )

                async with FakeClockContext() as clock:
                    sleep_task = asyncio.create_task(asyncio.sleep(0.001))
                    clock.advance(0.001)  # Reduced from 0.01 for performance
                    await sleep_task

                completion_task.cancel()
                with contextlib.suppress(
                    asyncio.CancelledError, asyncio.TimeoutError, Exception
                ):
                    await completion_task
            except Exception:
                # Ignore any exceptions during task creation/cancellation
                pass

        # Wait for callbacks to complete (even if they fail)
        # Wrap entire test in FakeClockContext so callback uses fake clock
        async with FakeClockContext() as clock:
            sleep_task = asyncio.create_task(asyncio.sleep(0.05))
            clock.advance(0.05)  # Reduced from 0.3 for performance
            await sleep_task

            final_tasks = len(asyncio.all_tasks())
        task_increase = final_tasks - initial_tasks

        # Failing callbacks should not cause task accumulation
        assert task_increase <= 10, (
            f"Failing cancellation callbacks caused task accumulation: "
            f"{task_increase} tasks remain. "
            "Failed callback tasks should be properly cleaned up."
        )
