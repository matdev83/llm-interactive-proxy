"""Backend completion flow orchestration service."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, cast
from uuid import uuid4

from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    LLMProxyError,
    NoForwardableContentError,
    NonForwardableEnforcementError,
    RateLimitExceededError,
    SessionCancelledError,
)
from src.core.domain.chat import CanonicalChatRequest, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_completion_collaborators import (
    IBackendAvailabilityChecker,
    IBackendInvoker,
    IBackendRequestPreparer,
    ICompletionSessionResolver,
    IFailureRecoveryExecutor,
    IUsageAccountingOrchestrator,
    IWireCaptureOrchestrator,
)
from src.core.interfaces.backend_completion_flow_interface import (
    IBackendCompletionFlow,
)
from src.core.interfaces.exception_normalizer_interface import IExceptionNormalizer
from src.core.interfaces.resilience_interface import IResilienceCoordinator
from src.core.interfaces.session_cancellation_coordinator_interface import (
    ISessionCancellationCoordinator,
)
from src.core.interfaces.non_forwardable_interface import (
    INonForwardableMessageEnforcer,
)
from src.core.interfaces.stream_formatting_interface import IStreamFormattingService
from src.core.services.resilience.scope import (
    build_resilience_error_context,
    build_resilience_instance_id,
)
from src.core.transport.session_key_resolver import (
    resolve_session_key_from_request_context,
)

# Import EoS adapter (optional dependency)
try:
    from src.core.services.backend_completion_flow.eos_adapter import (
        BackendCompletionFlowEosAdapter,
    )
except ImportError:
    BackendCompletionFlowEosAdapter = None  # type: ignore[assignment, misc]

logger = logging.getLogger(__name__)


class BackendCompletionFlow(IBackendCompletionFlow):
    """Orchestrates backend completion requests with failover, retry, and observability.

    This coordinator delegates substantial logic to focused collaborators:
    - BackendAvailabilityChecker: Availability gating (disabled backends, resilience checks)
    - CompletionSessionResolver: Session resolution and per-session backend selection
    - BackendRequestPreparer: Request preparation, config application, and target synchronization
    - BackendManager: Backend instance acquisition and lifecycle management
    - WireCaptureOrchestrator: Wire capture orchestration (outbound/inbound/errors)
    - UsageAccountingOrchestrator: Usage tracking, response wrapping, and accounting
    - FailureRecoveryExecutor: Failure recovery, retry, and failover execution

    The orchestrator owns flow ordering and shared context only. All substantial logic
    is delegated to collaborators to maintain clear boundaries and improve testability.

    Exception Handling Flow:
        Errors are handled in two layers:
        1. Inner exception handler: Catches exceptions from backend calls. When allow_failover=False,
           calls record_failure() and marks the exception to prevent double-processing.
        2. Outer exception handler: Catches exceptions that escape the inner handler (e.g., from
           apply_failure_recovery failures, auth failures that raise immediately). Calls record_failure()
           unless the exception is already marked as handled.

        The marker pattern (__handled_by_inner_handler__) prevents double-calling record_failure()
        when an exception propagates from inner to outer handler. This is necessary because:
        - When allow_failover=False, we call record_failure() in the inner handler before raising
        - The raised exception is caught by the outer handler
        - Without the marker, record_failure() would be called twice for the same error

    Raises:
        BackendError: If backend call fails and recovery is not possible
        RateLimitExceededError: If backend is rate limited
        AuthenticationError: If authentication fails
    """

    def __init__(
        self,
        availability_checker: IBackendAvailabilityChecker,
        request_preparer: IBackendRequestPreparer,
        session_resolver: ICompletionSessionResolver,
        backend_invoker: IBackendInvoker,
        failover_executor: IFailureRecoveryExecutor,
        wire_capture_orchestrator: IWireCaptureOrchestrator,
        usage_accounting_orchestrator: IUsageAccountingOrchestrator,
        exception_normalizer: IExceptionNormalizer,
        stream_formatting_service: IStreamFormattingService,
        resilience_coordinator: IResilienceCoordinator | None = None,
        eos_adapter: BackendCompletionFlowEosAdapter | None = None,  # type: ignore[invalid-type-form]
        cancellation_coordinator: ISessionCancellationCoordinator | None = None,
        non_forwardable_enforcer: INonForwardableMessageEnforcer | None = None,
    ) -> None:
        """Initialize the completion flow orchestrator."""
        self._availability_checker = availability_checker
        self._request_preparer = request_preparer
        self._session_resolver = session_resolver
        self._backend_invoker = backend_invoker
        self._failover_executor = failover_executor
        self._wire_capture_orchestrator = wire_capture_orchestrator
        self._usage_accounting = usage_accounting_orchestrator

        # Store dependencies needed for local logic
        self._resilience = resilience_coordinator
        self._exception_normalizer = exception_normalizer
        self._stream_formatting_service = stream_formatting_service
        self._eos_adapter = eos_adapter
        self._cancellation_coordinator = cancellation_coordinator
        self._non_forwardable_enforcer = non_forwardable_enforcer
        # Track cancellation tasks to prevent resource leaks
        self._cancellation_tasks: set[asyncio.Task[None]] = set()
        self._cancellation_tasks_lock = threading.Lock()

    def _attach_resilience_context(
        self,
        error: Exception,
        backend_type: str,
        context: RequestContext | None,
    ) -> None:
        """Attach resilience metadata to the error for handler decisions."""
        if getattr(error, "__resilience_context__", None) is not None:
            return
        error.__resilience_context__ = build_resilience_error_context(  # type: ignore[attr-defined]
            backend_type, context
        )

    def _record_failure(
        self,
        backend_type: str,
        effective_model: str,
        error: Exception,
        context: RequestContext | None,
    ) -> None:
        """Record failure with scoped instance id and attached context."""
        if not self._resilience:
            return
        instance_id = build_resilience_instance_id(backend_type, context)
        self._attach_resilience_context(error, backend_type, context)
        self._resilience.record_failure(instance_id, effective_model, error)

    def _cancellation_tasks_lock_sync_discard(self, task: asyncio.Task[None]) -> None:
        """Synchronous discard for task done callback - uses thread-unsafe dict access.

        This is safe because Python's GIL makes individual dict operations atomic,
        and done callbacks run one at a time in the event loop.
        """
        self._cancellation_tasks.discard(task)

    def _normalize_backend_exception(
        self, exc: Exception, backend_type: str
    ) -> Exception:
        candidate = self._exception_normalizer.normalize(exc, backend_type)

        if isinstance(candidate, Exception) and isinstance(candidate, LLMProxyError):
            # Preserve status_code from original exception if candidate doesn't have one
            if (
                not hasattr(candidate, "status_code")
                or getattr(candidate, "status_code", None) is None
            ):
                original_status_code = getattr(exc, "status_code", None)
                if isinstance(original_status_code, int):
                    candidate.status_code = original_status_code
            return candidate

        if (
            isinstance(candidate, Exception)
            and isinstance(getattr(candidate, "status_code", None), int)
            and not isinstance(candidate, LLMProxyError)
        ):
            # Fallback: ensure framework/transport exceptions (e.g. HTTPException) are
            # translated into domain errors even if an injected normalizer is mocked or
            # otherwise fails to translate them.
            from src.core.services.exception_normalizer import ExceptionNormalizer

            fallback_candidate = ExceptionNormalizer().normalize(
                candidate, backend_type
            )
            if isinstance(fallback_candidate, Exception) and isinstance(
                fallback_candidate, LLMProxyError
            ):
                return fallback_candidate

        if isinstance(candidate, Exception):
            return candidate

        # Preserve status_code from original exception when creating new BackendError
        original_status_code = getattr(exc, "status_code", None)
        normalized = BackendError(
            message=f"Backend call failed: {exc!s}",
            backend_name=backend_type,
            status_code=(
                original_status_code if isinstance(original_status_code, int) else None
            ),
        )
        normalized.__cause__ = exc
        return normalized

    async def call_completion(
        self,
        request: ChatRequest,
        stream: bool = False,
        allow_failover: bool = True,
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute completion orchestration with failover, retry, and observability."""
        canonical_request = (
            request
            if isinstance(request, CanonicalChatRequest)
            else CanonicalChatRequest.model_validate(request.model_dump())
        )
        # Step 1: Prepare request (resolve target + synchronize)
        target = await self._request_preparer.prepare_request(
            canonical_request, context
        )
        canonical_request = self._request_preparer.synchronize_request_with_target(
            canonical_request, target
        )
        backend_type = target.backend
        effective_model = target.model
        uri_params = target.uri_params

        # Step 2: Check if complex failover applies
        if allow_failover and await self._failover_executor.check_complex_failover(
            canonical_request, effective_model, backend_type, stream, context
        ):
            # Complex failover handled, return result
            return await self._failover_executor.execute_complex_failover(
                canonical_request,
                effective_model,
                backend_type,
                stream,
                self.call_completion,
                context,
            )

        # Step 3: Check backend availability (disabled + resilience)
        await self._availability_checker.check_backend_availability(
            backend_type, effective_model, allow_failover, context
        )

        # Step 4: Initialize failure strategy tracking
        start_time = time.time()
        attempted_backends: list[str] = []
        current_backend = backend_type
        content_started = False

        try:
            # Step 5: Resolve session
            (
                session,
                session_id_for_backend,
            ) = await self._session_resolver.resolve_session(context, canonical_request)

            # Step 6: Acquire backend instance
            backend = await self._backend_invoker.acquire_backend(
                backend_type, session_id_for_backend
            )

            # Step 7: Prepare backend request (configs + URI params)
            domain_request = await self._request_preparer.prepare_backend_request(
                canonical_request, backend_type, session, uri_params
            )

            # Step 7.5: Apply non-forwardable message filtering
            # This happens after history compaction (if enabled) and before wire capture
            # to ensure filtered messages are used for both capture and backend calls
            if self._non_forwardable_enforcer is not None:
                # Ensure session_id is non-empty (requirement 8.1)
                # Generate a new session ID if none was resolved
                if not session_id_for_backend:
                    session_id_for_backend = str(uuid4())
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Generated new session ID for non-forwardable enforcement: %s",
                            session_id_for_backend,
                        )

                try:
                    filtered_messages, filtered_count = (
                        await self._non_forwardable_enforcer.filter_messages(
                            session_id=session_id_for_backend,
                            messages=domain_request.messages,
                            context=context,
                        )
                    )

                    # Update both canonical_request and domain_request with filtered messages
                    canonical_request = canonical_request.model_copy(
                        update={"messages": filtered_messages}
                    )
                    domain_request = domain_request.model_copy(
                        update={"messages": filtered_messages}
                    )

                    # Log filtering decision if messages were filtered (requirement 6.1, 6.2)
                    if filtered_count > 0 and logger.isEnabledFor(logging.INFO):
                        log_extra = {
                            "session_id": session_id_for_backend,
                            "filtered_count": filtered_count,
                            "remaining_count": len(filtered_messages),
                        }
                        # Include request correlation identifier if available (requirement 6.1)
                        if context and context.request_id:
                            log_extra["request_id"] = context.request_id
                        logger.info(
                            "Filtered non-forwardable messages from backend request",
                            extra=log_extra,
                        )
                except (NoForwardableContentError, NonForwardableEnforcementError) as e:
                    # Fail closed: do not proceed with backend call
                    raise BackendError(
                        message=f"Non-forwardable message enforcement failed: {e!s}",
                        backend_name=backend_type,
                    ) from e

            # Step 8: Prepare wire capture context (identity + backend config)
            identity = (
                await self._wire_capture_orchestrator.prepare_wire_capture_context(
                    backend_type, session
                )
            )

            # Step 9: Execute backend call (with wire capture + usage tracking)
            result: ResponseEnvelope | StreamingResponseEnvelope | None = None
            try:
                # Wire-capture: capture outbound payload pre-call (best-effort)
                await self._wire_capture_orchestrator.capture_wire_outbound(
                    backend_type=backend_type,
                    effective_model=effective_model,
                    domain_request=domain_request,
                    context=context,
                )

                # Resolve SessionKey for cancellation gating
                session_key = resolve_session_key_from_request_context(context)

                # Cancellation gate: ensure session is not cancelled before backend call
                if (
                    self._cancellation_coordinator is not None
                    and session_key is not None
                ):
                    self._cancellation_coordinator.ensure_not_cancelled(session_key)

                # Prepare backend call kwargs
                backend_call_kwargs = self._request_preparer.prepare_backend_kwargs(
                    session_id_for_backend=session_id_for_backend,
                    session=session,
                    context=context,
                    backend_type=backend_type,
                )

                # Calculate outbound tokens and record usage
                (
                    outbound_tokens,
                    ctp_record_id,
                    ptb_record_id,
                ) = await self._usage_accounting.calculate_and_record_usage(
                    domain_request=domain_request,
                    request=canonical_request,
                    backend_type=backend_type,
                    effective_model=effective_model,
                    session=session,
                    session_id_for_backend=session_id_for_backend,
                )

                # Execute the backend call
                result = await backend.chat_completions(
                    request_data=domain_request,
                    processed_messages=canonical_request.messages,
                    effective_model=effective_model,
                    identity=identity,
                    cancellation_token=session_key,
                    cancellation_coordinator=self._cancellation_coordinator,
                    **backend_call_kwargs,
                )

                # Register cancellable work if coordinator and session_key are available
                if (
                    self._cancellation_coordinator is not None
                    and session_key is not None
                ):
                    from src.core.interfaces.session_cancellation_coordinator_interface import (
                        ICancellable,
                    )

                    # Create cancellable wrapper for streaming responses
                    if (
                        isinstance(result, StreamingResponseEnvelope)
                        and result.cancel_callback is not None
                    ):

                        class StreamingCancellable:
                            """Cancellable wrapper for streaming backend work."""

                            def __init__(
                                self,
                                cancel_callback: Callable[[], Awaitable[None]],
                                cancellation_tasks: set[asyncio.Task[None]],
                            ):
                                self._cancel_callback = cancel_callback
                                self._cancelled: bool = False
                                self._cancellation_tasks = cancellation_tasks

                            def cancel(self) -> None:
                                """Cancel streaming backend work."""
                                if not self._cancelled:
                                    self._cancelled = True
                                    # Schedule cancellation callback execution
                                    try:
                                        loop = asyncio.get_running_loop()
                                        # Call cancel_callback to get coroutine, then create task and track it
                                        coro = self._cancel_callback()
                                        # Type cast: cancel_callback returns Awaitable[None] but create_task expects Coroutine
                                        # In practice, create_task accepts coroutines which are a subtype of Awaitable
                                        coroutine: Coroutine[Any, Any, None] = cast(
                                            Coroutine[Any, Any, None], coro
                                        )
                                        task: asyncio.Task[None] = loop.create_task(
                                            coroutine
                                        )
                                        # Track task to prevent resource leaks
                                        self._cancellation_tasks.add(task)
                                        # Remove task from set when done to prevent unbounded growth
                                        task.add_done_callback(
                                            self._cancellation_tasks.discard
                                        )
                                    except RuntimeError:
                                        # No event loop, skip cancellation
                                        pass

                        cancellable: ICancellable = StreamingCancellable(
                            result.cancel_callback,
                            self._cancellation_tasks,
                        )
                        self._cancellation_coordinator.register_cancellable(
                            session_key, cancellable
                        )
                    # For non-streaming responses, HTTP calls are typically fast
                    # and gating prevents new calls, so we skip registration

                # Wrap result for usage tracking
                assert result is not None, "Backend call must return a response"
                result = await self._usage_accounting.wrap_response_for_usage(
                    result=result,
                    outbound_tokens=outbound_tokens,
                    ctp_record_id=ctp_record_id,
                    ptb_record_id=ptb_record_id,
                    start_time=start_time,
                    context=context,
                    backend_type=backend_type,
                    effective_model=effective_model,
                )

                # Step 10: Handle streaming response (wire capture + session ID injection)
                if isinstance(result, StreamingResponseEnvelope):
                    # Wire-capture: capture inbound stream
                    key_name = self._wire_capture_orchestrator.detect_key_name(
                        backend_type
                    )
                    session_id = getattr(context, "session_id", None)

                    if result.content is not None:
                        # Adapt domain stream to bytes for capture
                        byte_stream = (
                            self._stream_formatting_service.stream_as_sse_bytes(
                                result.content
                            )
                        )
                        wrapped_stream = (
                            self._wire_capture_orchestrator.wrap_inbound_stream(
                                context=context,
                                session_id=session_id,
                                backend_type=backend_type,
                                effective_model=effective_model,
                                key_name=key_name,
                                stream=byte_stream,
                            )
                        )

                        # Convert back to ProcessedResponse stream for adapters
                        async def _to_processed_with_capture() -> Any:
                            from src.core.interfaces.response_processor_interface import (
                                ProcessedResponse,
                            )

                            async for b in wrapped_stream:
                                yield ProcessedResponse(content=b, metadata={})

                        result.content = _to_processed_with_capture()  # type: ignore[assignment]

                    streaming_result = (
                        await self._usage_accounting.handle_streaming_response(
                            result=result,
                            backend_type=backend_type,
                            effective_model=effective_model,
                            context=context,
                            request=domain_request,
                            session_id_for_backend=session_id_for_backend,
                            key_name=key_name,
                        )
                    )

                    # Note: canonical_usage capture is now handled inside
                    # handle_streaming_response's finally block, which executes
                    # when the stream completes (not here, before stream consumption)

                    # Check cancellation status before returning streaming result
                    # If cancelled, treat result as non-deliverable
                    if (
                        self._cancellation_coordinator is not None
                        and session_key is not None
                        and self._cancellation_coordinator.is_cancelled(session_key)
                    ):
                        if logger.isEnabledFor(logging.INFO):
                            logger.info(
                                "Backend call completed but session was cancelled - "
                                "treating streaming result as non-deliverable",
                                extra={"session_key": session_key.primary_id},
                            )
                        raise SessionCancelledError(session_key=session_key)

                    return streaming_result

                # Step 11: Handle non-streaming response
                # Wire-capture: capture inbound response
                key_name = self._wire_capture_orchestrator.detect_key_name(backend_type)
                # Serialize content for capture (best effort)
                response_content: Any = result
                if hasattr(result, "model_dump") and not isinstance(result, dict):
                    response_content = result.model_dump()  # type: ignore[attr-defined]
                elif hasattr(result, "__dict__"):
                    response_content = result.__dict__

                # Extract canonical usage from envelope if present
                canonical_usage_for_capture: dict[str, Any] | None = None
                if (
                    hasattr(result, "canonical_usage")
                    and result.canonical_usage is not None
                ):
                    canonical_usage_for_capture = result.canonical_usage.model_dump()

                await self._wire_capture_orchestrator.capture_inbound_response(
                    context=context,
                    session_id=getattr(context, "session_id", None),
                    backend_type=backend_type,
                    effective_model=effective_model,
                    key_name=key_name,
                    response_content=response_content,
                    canonical_usage=canonical_usage_for_capture,
                )

                # Check cancellation status before returning non-streaming result
                # If cancelled, treat result as non-deliverable
                if (
                    self._cancellation_coordinator is not None
                    and session_key is not None
                    and self._cancellation_coordinator.is_cancelled(session_key)
                ):
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Backend call completed but session was cancelled - "
                            "treating non-streaming result as non-deliverable",
                            extra={"session_key": session_key.primary_id},
                        )
                    raise SessionCancelledError(session_key=session_key)

                return await self._usage_accounting.handle_non_streaming_response(
                    result=result,
                    backend_type=backend_type,
                    effective_model=effective_model,
                    session_id_for_backend=session_id_for_backend,
                    context=context,
                )

            except asyncio.CancelledError:
                raise
            except SessionCancelledError:
                # Preserve SessionCancelledError - do not normalize
                raise
            except Exception as call_exc:
                # Normalize the exception immediately for consistent handling
                normalized_exc = self._normalize_backend_exception(
                    call_exc, backend_type
                )
                # Safety check: ensure normalized_exc is actually an Exception
                if not isinstance(normalized_exc, Exception):
                    normalized_exc = BackendError(
                        message=f"Backend call failed: {call_exc!s}",
                        backend_name=backend_type,
                    )
                    normalized_exc.__cause__ = call_exc

                # Check if this is an authentication failure first
                is_auth_failure = False
                if isinstance(normalized_exc, AuthenticationError) or (
                    hasattr(normalized_exc, "status_code")
                    and getattr(normalized_exc, "status_code", None) == 401
                ):
                    is_auth_failure = True

                if is_auth_failure:
                    # Handle authentication failures with backend lifecycle side effects
                    await self._usage_accounting.handle_auth_failure(
                        normalized_exc,
                        backend,
                        backend_type,
                        session_id_for_backend,
                    )
                    raise normalized_exc

                # Handle backend error (wire capture + usage/resilience updates)
                # 1. Wire capture error
                key_name = self._wire_capture_orchestrator.detect_key_name(backend_type)
                error_payload: dict[str, Any]
                if isinstance(normalized_exc, LLMProxyError):
                    error_payload = normalized_exc.to_dict()
                    # Ensure status code is present if available
                    import contextlib

                    with contextlib.suppress(Exception):
                        if (
                            isinstance(error_payload.get("error"), dict)
                            and "status_code" not in error_payload["error"]
                        ):
                            error_payload["error"]["status_code"] = getattr(
                                normalized_exc, "status_code", None
                            )
                else:
                    error_payload = {
                        "error": {
                            "message": str(normalized_exc),
                            "type": type(normalized_exc).__name__,
                        }
                    }

                # Extract canonical usage from envelope if present (may be None for errors)
                canonical_usage_for_error: dict[str, Any] | None = None
                if (
                    result is not None
                    and isinstance(result, ResponseEnvelope)
                    and result.canonical_usage is not None
                ):
                    canonical_usage_for_error = result.canonical_usage.model_dump()
                # Note: For error cases, canonical_usage may not be available

                await self._wire_capture_orchestrator.capture_inbound_response(
                    context=context,
                    session_id=getattr(context, "session_id", None),
                    backend_type=backend_type,
                    effective_model=effective_model,
                    key_name=key_name,
                    response_content=error_payload,
                    canonical_usage=canonical_usage_for_error,
                )

                # 2. Update resilience/usage via accounting collaborator
                await self._usage_accounting.handle_backend_error(
                    call_exc=call_exc,
                    backend_type=current_backend,
                    effective_model=effective_model,
                    context=context,
                    request=canonical_request,
                    backend=backend,
                    normalized_exc=normalized_exc,
                )

                # 3. Record EoS error termination signal (fail-open)
                if self._eos_adapter is not None:
                    try:
                        await self._eos_adapter.record_error_termination(
                            error=normalized_exc,
                            session_id=session_id_for_backend,
                            backend_type=current_backend,
                            context=context,
                        )
                    except Exception as eos_error:
                        # Fail-open: log but don't interfere with error handling
                        logger.warning(
                            "Failed to record EoS error termination: %s",
                            eos_error,
                            exc_info=True,
                        )

                # Step 13: Apply failure recovery (retry/failover)
                if allow_failover:
                    return await self._failover_executor.apply_failure_recovery(
                        error=normalized_exc,
                        model=effective_model,
                        backend_type=current_backend,
                        attempted_backends=attempted_backends,
                        start_time=start_time,
                        is_streaming=stream,
                        content_started=content_started,
                        request=canonical_request,
                        context=context,
                        call_completion_callback=self.call_completion,
                    )

                # No failover allowed - record failure and raise the normalized error
                # According to Requirement 4.4: record_failure must be called when backend
                # call fails, before re-raising the exception.
                # We mark the exception to prevent double-calling when it propagates to
                # the outer exception handler (which also calls record_failure for exceptions
                # that escape the inner handler, e.g., from apply_failure_recovery failures).
                if self._resilience:
                    self._record_failure(
                        current_backend, effective_model, normalized_exc, context
                    )
                    # Mark as handled to prevent outer handler from calling record_failure again.
                    # This marker is necessary because when allow_failover=False, we call
                    # record_failure here and then raise, which will be caught by the outer
                    # handler. Without this marker, record_failure would be called twice for
                    # the same error.
                    normalized_exc.__handled_by_inner_handler__ = True  # type: ignore[attr-defined]
                raise normalized_exc

        except asyncio.CancelledError:
            raise
        except SessionCancelledError:
            # Preserve SessionCancelledError - do not normalize
            raise
        except (
            BackendError,
            RateLimitExceededError,
            LLMProxyError,
            AuthenticationError,
        ) as exc:
            # Record failure in resilience coordinator (handles cooldown/backoff).
            # This outer handler catches exceptions that escape the inner handler:
            # 1. Exceptions from apply_failure_recovery when allow_failover=True
            # 2. Exceptions from auth failure handling (which raises immediately)
            # 3. Unexpected exceptions that bypass the inner handler
            # We skip if already handled in inner handler (when allow_failover=False)
            # to avoid double-calling record_failure for the same error.
            if self._resilience and not getattr(
                exc, "__handled_by_inner_handler__", False
            ):
                self._record_failure(backend_type, effective_model, exc, context)

            # Record EoS error termination signal (fail-open)
            if self._eos_adapter is not None:
                try:
                    session_id = (
                        getattr(context, "session_id", None) if context else None
                    )
                    await self._eos_adapter.record_error_termination(
                        error=exc,
                        session_id=session_id,
                        backend_type=backend_type,
                        context=context,
                    )
                except Exception as eos_error:
                    # Fail-open: log but don't interfere with error handling
                    logger.warning(
                        "Failed to record EoS error termination: %s",
                        eos_error,
                        exc_info=True,
                    )

            # Propagate expected exceptions as-is
            raise
        except Exception as exc:
            # Normalize any remaining "foreign" exception into a domain error to keep
            # transport/framework types out of the service boundary.
            normalized_exc = self._normalize_backend_exception(exc, backend_type)

            # Record EoS error termination signal (fail-open)
            if self._eos_adapter is not None:
                try:
                    session_id = (
                        getattr(context, "session_id", None) if context else None
                    )
                    await self._eos_adapter.record_error_termination(
                        error=normalized_exc,
                        session_id=session_id,
                        backend_type=backend_type,
                        context=context,
                    )
                except Exception as eos_error:
                    # Fail-open: log but don't interfere with error handling
                    logger.warning(
                        "Failed to record EoS error termination: %s",
                        eos_error,
                        exc_info=True,
                    )

            if isinstance(normalized_exc, LLMProxyError):
                raise normalized_exc from exc

            raise BackendError(
                message=f"Backend call failed: {exc!s}",
                backend_name=backend_type,
            ) from exc

    async def cleanup(self) -> None:
        """Clean up pending cancellation tasks to prevent resource leaks.

        This method cancels and awaits all pending cancellation tasks.
        Should be called during application shutdown to ensure all resources
        are properly released.
        """
        # Take snapshot of pending tasks
        with self._cancellation_tasks_lock:
            pending_tasks = [t for t in self._cancellation_tasks if not t.done()]
        if pending_tasks:
            try:
                # Cancel all pending tasks
                for task in pending_tasks:
                    if not task.done():
                        task.cancel()
                # Await cancelled tasks to ensure they complete
                # Note: gather() with return_exceptions=True shouldn't raise,
                # but RuntimeError can occur if event loop is closed
                await asyncio.gather(*pending_tasks, return_exceptions=True)
            except RuntimeError as err:
                # RuntimeError: event loop closed or other infrastructure issues
                logger.warning(
                    "Error during cancellation task cleanup (event loop issue): %s; suppressing to allow cleanup to continue",
                    err,
                    exc_info=True,
                    extra={"pending_tasks_count": len(pending_tasks)},
                )
            except Exception as err:
                # Defensive catch for any other unexpected errors during cleanup
                logger.warning(
                    "Unexpected error during cancellation task cleanup: %s (%s); suppressing to allow cleanup to continue",
                    err,
                    type(err).__name__,
                    exc_info=True,
                    extra={"pending_tasks_count": len(pending_tasks)},
                )
            finally:
                # Clear set to prevent memory leaks
                with self._cancellation_tasks_lock:
                    self._cancellation_tasks.clear()
