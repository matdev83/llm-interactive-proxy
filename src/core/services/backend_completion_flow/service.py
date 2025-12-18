"""Backend completion flow orchestration service."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    LLMProxyError,
    RateLimitExceededError,
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
from src.core.interfaces.stream_formatting_interface import IStreamFormattingService

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

    def _normalize_backend_exception(
        self, exc: Exception, backend_type: str
    ) -> Exception:
        candidate = self._exception_normalizer.normalize(exc, backend_type)

        if isinstance(candidate, Exception) and isinstance(candidate, LLMProxyError):
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

        normalized = BackendError(
            message=f"Backend call failed: {exc!s}",
            backend_name=backend_type,
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
            backend_type, effective_model, allow_failover
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

            # Step 8: Prepare wire capture context (identity + backend config)
            identity = (
                await self._wire_capture_orchestrator.prepare_wire_capture_context(
                    backend_type, session
                )
            )

            # Step 9: Execute backend call (with wire capture + usage tracking)
            try:
                # Wire-capture: capture outbound payload pre-call (best-effort)
                await self._wire_capture_orchestrator.capture_wire_outbound(
                    backend_type=backend_type,
                    effective_model=effective_model,
                    domain_request=domain_request,
                    context=context,
                )

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
                result: ResponseEnvelope | StreamingResponseEnvelope = (
                    await backend.chat_completions(
                        request_data=domain_request,
                        processed_messages=canonical_request.messages,
                        effective_model=effective_model,
                        identity=identity,
                        **backend_call_kwargs,
                    )
                )

                # Wrap result for usage tracking
                result = await self._usage_accounting.wrap_response_for_usage(
                    result=result,
                    outbound_tokens=outbound_tokens,
                    ctp_record_id=ctp_record_id,
                    ptb_record_id=ptb_record_id,
                    start_time=start_time,
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

                        result.content = _to_processed_with_capture()

                    return await self._usage_accounting.handle_streaming_response(
                        result=result,
                        backend_type=backend_type,
                        effective_model=effective_model,
                        context=context,
                        request=domain_request,
                        session_id_for_backend=session_id_for_backend,
                    )

                # Step 11: Handle non-streaming response
                # Wire-capture: capture inbound response
                key_name = self._wire_capture_orchestrator.detect_key_name(backend_type)
                # Serialize content for capture (best effort)
                response_content: Any = result
                if hasattr(result, "model_dump"):
                    response_content = result.model_dump()
                elif hasattr(result, "__dict__"):
                    response_content = result.__dict__

                await self._wire_capture_orchestrator.capture_inbound_response(
                    context=context,
                    session_id=getattr(context, "session_id", None),
                    backend_type=backend_type,
                    effective_model=effective_model,
                    key_name=key_name,
                    response_content=response_content,
                )

                return await self._usage_accounting.handle_non_streaming_response(
                    result=result,
                    backend_type=backend_type,
                    effective_model=effective_model,
                    session_id_for_backend=session_id_for_backend,
                )

            except asyncio.CancelledError:
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

                await self._wire_capture_orchestrator.capture_inbound_response(
                    context=context,
                    session_id=getattr(context, "session_id", None),
                    backend_type=backend_type,
                    effective_model=effective_model,
                    key_name=key_name,
                    response_content=error_payload,
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

                # No failover allowed, raise the normalized error
                raise normalized_exc

        except asyncio.CancelledError:
            raise
        except (
            BackendError,
            RateLimitExceededError,
            LLMProxyError,
            AuthenticationError,
        ) as exc:
            # Record failure in resilience coordinator (handles cooldown/backoff)
            if self._resilience:
                self._resilience.record_failure(backend_type, effective_model, exc)
            # Propagate expected exceptions as-is
            raise
        except Exception as exc:
            # Normalize any remaining "foreign" exception into a domain error to keep
            # transport/framework types out of the service boundary.
            normalized_exc = self._normalize_backend_exception(exc, backend_type)
            if isinstance(normalized_exc, LLMProxyError):
                raise normalized_exc from exc

            raise BackendError(
                message=f"Backend call failed: {exc!s}",
                backend_name=backend_type,
            ) from exc
