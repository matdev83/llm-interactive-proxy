"""Failure recovery execution collaborator."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic.types import JsonValue

from src.core.common.exceptions import (
    BackendError,
    LLMProxyError,
    RateLimitExceededError,
)
from src.core.domain.chat import CanonicalChatRequest, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_completion_collaborators import (
    IFailureRecoveryExecutor,
)
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.failover_planner_interface import IFailoverPlanner
from src.core.interfaces.failure_strategy_interface import (
    FailureDecision,
    IFailureHandlingStrategy,
)
from src.core.services.backend_routing_service import BackendRoutingService

logger = logging.getLogger(__name__)


class FailureRecoveryExecutor(IFailureRecoveryExecutor):
    """Handles failover planning and execution."""

    def __init__(
        self,
        failover_planner: IFailoverPlanner,
        failure_handling_strategy: IFailureHandlingStrategy | None,
        routing_service: BackendRoutingService | None,
        config: IConfig,
        failover_routes: dict[str, dict[str, Any]] | None = None,
    ):
        """Initialize the failure recovery executor."""
        self._failover_planner = failover_planner
        self._failure_strategy = failure_handling_strategy
        self._routing_service = routing_service
        self._config = config
        self._failover_routes = failover_routes or {}

    async def check_complex_failover(
        self,
        request: CanonicalChatRequest,
        effective_model: str,
        backend_type: str,
        stream: bool,
        context: RequestContext | None = None,
    ) -> bool:
        """Check if complex failover should be executed for this request."""
        request_failover_routes: dict[str, Any] | None = (
            request.extra_body.get("failover_routes") if request.extra_body else None
        )
        effective_failover_routes: dict[str, Any] = (
            request_failover_routes
            if request_failover_routes
            else self._failover_routes
        )

        return effective_model in effective_failover_routes

    async def execute_complex_failover(
        self,
        request: CanonicalChatRequest,
        effective_model: str,
        backend_type: str,
        stream: bool,
        call_completion_callback: Callable[
            ..., Awaitable[ResponseEnvelope | StreamingResponseEnvelope]
        ],
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute complex failover strategy for models with configured routes."""
        if logger.isEnabledFor(logging.INFO):
            logger.info(f"Using complex failover policy for model {effective_model}")

        try:
            from src.core.domain.configuration.backend_config import (
                BackendConfiguration,
            )

            request_failover_routes: dict[str, Any] | None = (
                request.extra_body.get("failover_routes")
                if request.extra_body
                else None
            )
            effective_failover_routes: dict[str, Any] = (
                request_failover_routes
                if request_failover_routes
                else self._failover_routes
            )

            # Instantiate for validation side effects
            _ = BackendConfiguration(
                backend_type=backend_type,
                model=effective_model,
                failover_routes_data=effective_failover_routes,
            )

            plan: list[tuple[str, str]] = self._failover_planner.get_failover_plan(
                effective_model, backend_type
            )

            return await self.attempt_failover_plan(
                request, plan, stream, backend_type, call_completion_callback, context
            )
        except BackendError:
            raise
        except (TypeError, ValueError, AttributeError, KeyError) as failover_error:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Failover processing failed: {failover_error!s}", exc_info=True
                )
            raise BackendError(
                message="all backends failed", backend_name=backend_type
            ) from failover_error

    async def attempt_failover_plan(
        self,
        request: ChatRequest,
        plan: list[tuple[str, str]],
        stream: bool,
        backend_type: str,
        call_completion_callback: Callable[
            ..., Awaitable[ResponseEnvelope | StreamingResponseEnvelope]
        ],
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Attempt failover using the provided plan."""
        last_error: Exception | None = None
        if not plan:
            raise BackendError(message="all backends failed", backend_name=backend_type)

        for backend_attempt, model_attempt in plan:
            try:
                attempt_extra_body: dict[str, Any] = (
                    request.extra_body.copy() if request.extra_body else {}
                )
                attempt_extra_body["backend_type"] = backend_attempt

                attempt_request: ChatRequest = request.model_copy(
                    update={
                        "extra_body": attempt_extra_body,
                        "model": model_attempt,
                    }
                )

                return await call_completion_callback(
                    request=attempt_request,
                    stream=stream,
                    allow_failover=False,
                    context=context,
                )
            except (BackendError, RateLimitExceededError) as attempt_error:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Failover attempt failed for {backend_attempt}:{model_attempt}: {attempt_error!s}",
                        exc_info=True,
                    )
                last_error = attempt_error
                continue
            except Exception as attempt_error:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        f"Unexpected error during failover attempt for {backend_attempt}:{model_attempt}: {attempt_error!s}",
                        exc_info=True,
                    )
                last_error = attempt_error
                continue

        if last_error:
            raise BackendError(
                message=f"All failover attempts failed. Last error: {last_error!s}",
                backend_name=backend_type,
            )
        else:
            raise BackendError(
                message="All failover attempts failed. No error details available.",
                backend_name=backend_type,
            )

    async def apply_failure_strategy(
        self,
        error: BackendError,
        model: str,
        backend_type: str,
        attempted_backends: list[str],
        start_time: float,
        is_streaming: bool,
        content_started: bool,
    ) -> tuple[FailureDecision, float | None, str | None]:
        """Apply failure handling strategy to decide how to handle a backend failure."""
        if self._failure_strategy is None:
            # No failure strategy configured, surface all errors
            return FailureDecision.SURFACE_ERROR, None, None

        elapsed_time = time.time() - start_time

        # Find available backend alternatives
        available_backends: list[str] | None = None
        if self._routing_service is not None:
            available_backends = self._routing_service.find_alternative_instances(
                model, [*attempted_backends, backend_type]
            )

        result = self._failure_strategy.decide(
            error=error,
            model=model,
            current_backend=backend_type,
            attempted_backends=attempted_backends,
            elapsed_time=elapsed_time,
            is_streaming=is_streaming,
            content_started=content_started,
            available_backends=available_backends,
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Failure strategy decision for %s/%s: %s (reason: %s)",
                backend_type,
                model,
                result.decision.value,
                result.reason,
            )

        return result.decision, result.wait_seconds, result.next_backend

    async def execute_retry(
        self,
        request: ChatRequest,
        backend_type: str,
        wait_seconds: float | None,
        is_streaming: bool,
        model: str,
        attempted_backends: list[str],
        call_completion_callback: Callable[
            ..., Awaitable[ResponseEnvelope | StreamingResponseEnvelope]
        ],
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute retry of the same backend after waiting."""
        if wait_seconds is not None and wait_seconds > 0:
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Failure strategy: waiting %.1fs before retrying %s/%s",
                    wait_seconds,
                    backend_type,
                    model,
                )
            # Only sleep here for non-streaming requests
            if not (is_streaming or getattr(request, "stream", False)):
                await asyncio.sleep(wait_seconds)

        # Remove from attempted to allow retry
        if attempted_backends and attempted_backends[-1] == backend_type:
            attempted_backends.pop()

        # Create modified request to retry same backend
        retry_request = request.model_copy(
            update={
                "extra_body": {
                    **(request.extra_body or {}),
                    "backend_type": backend_type,
                }
            }
        )

        # For streaming, send keepalives during the wait
        if is_streaming or getattr(request, "stream", False):
            from src.core.services.streaming_keepalive import KeepAliveGenerator

            capture_session_id = None
            if context is not None:
                capture_session_id = getattr(context, "session_id", None)

            async def _wait_and_retry_stream() -> Any:
                # 1. Yield keepalives during the wait
                if wait_seconds and wait_seconds > 0:
                    # Use configured keepalive interval or default
                    ka_interval = 8.0
                    if hasattr(self._config, "failure_handling"):
                        ka_interval = getattr(
                            self._config.failure_handling,
                            "keepalive_interval",
                            8.0,
                        )

                    async for chunk in KeepAliveGenerator(
                        wait_seconds=wait_seconds,
                        interval_seconds=ka_interval,
                        include_status=True,
                        model=model,
                        session_id=capture_session_id,
                        stream_id=capture_session_id,
                    ):
                        yield chunk

                # 2. Execute retry
                try:
                    result = await call_completion_callback(
                        request=retry_request,
                        stream=True,
                        allow_failover=True,
                        context=context,
                    )

                    # 3. Yield from the successful retry
                    if isinstance(result, StreamingResponseEnvelope):
                        async for chunk in result.content:  # type: ignore
                            yield chunk
                    else:
                        yield result.content
                except Exception as e:
                    logger.error(f"Retry failed during stream: {e}", exc_info=True)
                    from src.core.interfaces.response_processor_interface import (
                        ProcessedResponse,
                    )

                    error_details: dict[str, JsonValue] = {
                        "type": type(e).__name__,
                        "message": str(e),
                        "retryable": False,
                    }
                    yield ProcessedResponse(
                        content={
                            "choices": [
                                {
                                    "delta": {},
                                    "finish_reason": "error",
                                    "index": 0,
                                }
                            ],
                            "error": error_details,
                        },
                        metadata={
                            "finish_reason": "error",
                            "error": error_details,
                            "is_done": True,
                            "model": model,
                        },
                        usage=None,
                    )

            return StreamingResponseEnvelope(
                content=_wait_and_retry_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            )

        # Non-streaming: just recurse after sleep (already slept above)
        return await call_completion_callback(
            request=retry_request,
            stream=is_streaming,
            allow_failover=True,
            context=context,
        )

    async def execute_failover(
        self,
        request: ChatRequest,
        next_backend: str,
        is_streaming: bool,
        backend_type: str,
        model: str,
        call_completion_callback: Callable[
            ..., Awaitable[ResponseEnvelope | StreamingResponseEnvelope]
        ],
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute failover to an alternative backend."""
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Failure strategy: failing over from %s to %s for model %s",
                backend_type,
                next_backend,
                model,
            )

        # Create request targeting the new backend
        failover_request = request.model_copy(
            update={
                "extra_body": {
                    **(request.extra_body or {}),
                    "backend_type": next_backend,
                }
            }
        )

        return await call_completion_callback(
            request=failover_request,
            stream=is_streaming,
            allow_failover=True,
            context=context,
        )

    async def apply_failure_recovery(
        self,
        error: Exception,
        model: str,
        backend_type: str,
        attempted_backends: list[str],
        start_time: float,
        is_streaming: bool,
        content_started: bool,
        request: CanonicalChatRequest,
        call_completion_callback: Callable[
            ..., Awaitable[ResponseEnvelope | StreamingResponseEnvelope]
        ],
        context: RequestContext | None = None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Apply failure handling strategy to decide retry/failover."""
        # Track this backend as attempted
        if backend_type not in attempted_backends:
            attempted_backends.append(backend_type)

        # Check if we have a failure strategy configured
        if self._failure_strategy is None:
            logger.warning(
                "No failure handling strategy configured - errors will not "
                "be retried automatically. Consider configuring a failure strategy."
            )
            if isinstance(error, BackendError | RateLimitExceededError | LLMProxyError):
                raise error
            raise BackendError(
                message=f"Backend call failed: {error!s}",
                backend_name=backend_type,
            ) from error

        # Normalize the error for the strategy
        normalized_error = (
            error
            if isinstance(error, BackendError)
            else BackendError(
                message=str(error),
                backend_name=backend_type,
            )
        )
        # Consult the failure strategy
        failure_decision, wait_seconds, next_backend = (
            await self.apply_failure_strategy(
                error=normalized_error,
                model=model,
                backend_type=backend_type,
                attempted_backends=attempted_backends,
                start_time=start_time,
                is_streaming=is_streaming,
                content_started=content_started,
            )
        )
        if failure_decision == FailureDecision.WAIT_AND_RETRY:
            return await self.execute_retry(
                request=request,
                backend_type=backend_type,
                wait_seconds=wait_seconds,
                is_streaming=is_streaming,
                model=model,
                attempted_backends=attempted_backends,
                call_completion_callback=call_completion_callback,
                context=context,
            )
        if (
            failure_decision == FailureDecision.FAILOVER_IMMEDIATE
            and next_backend is not None
        ):
            return await self.execute_failover(
                request=request,
                next_backend=next_backend,
                is_streaming=is_streaming,
                backend_type=backend_type,
                model=model,
                call_completion_callback=call_completion_callback,
                context=context,
            )
        # SURFACE_ERROR or no next backend - raise the error
        if isinstance(error, BackendError | RateLimitExceededError | LLMProxyError):
            raise error

        # Preserve HTTP status code if available (duck typing for transport exceptions)
        status_code = None
        if hasattr(error, "status_code"):
            status_code = getattr(error, "status_code", None)

        raise BackendError(
            message=f"Backend call failed: {error!s}",
            backend_name=backend_type,
            status_code=status_code,
        ) from error
