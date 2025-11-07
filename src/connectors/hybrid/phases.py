"""Execution phases for the hybrid connector."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.connectors.hybrid.constants import (
    EXECUTION_PHASE_TIMEOUT,
    REASONING_PHASE_TIMEOUT,
)
from src.connectors.hybrid.types import ReasoningPhaseResult
from src.connectors.utils.model_capabilities import (
    get_execution_params,
    get_reasoning_params,
)
from src.core.common.exceptions import BackendError, ServiceResolutionError
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO

logger = logging.getLogger(__name__)


class HybridPhaseMixin:
    """Manage the two-phase hybrid execution flow."""

    _backend_registry: Any

    async def _execute_reasoning_phase(
        self,
        messages: list,
        reasoning_backend: str,
        reasoning_model: str,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        identity: IAppIdentityConfig | None,
        uri_params: dict[str, Any] | None = None,
    ) -> ReasoningPhaseResult:
        """Execute reasoning phase and capture output and metadata."""

        logger.info(
            "Starting reasoning phase with %s:%s",
            reasoning_backend,
            reasoning_model,
        )

        if self._backend_registry is None:
            logger.error("Backend registry not initialized for reasoning phase")
            raise BackendError(
                message="Backend registry not initialized",
                code="backend_registry_not_initialized",
                details={
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                },
            )

        reasoning_preset_params = get_reasoning_params(reasoning_backend)
        reasoning_request = self._apply_reasoning_params(
            request_data, reasoning_preset_params
        )

        if uri_params:
            try:
                from src.core.services.uri_parameter_validator import (
                    URIParameterValidator,
                )

                validator = URIParameterValidator()
                normalized_params, validation_errors = validator.validate_and_normalize(
                    uri_params
                )

                if validation_errors:
                    logger.warning(
                        "URI parameter validation errors for reasoning phase (%s:%s): %s. Invalid parameters will be excluded.",
                        reasoning_backend,
                        reasoning_model,
                        ", ".join(validation_errors),
                    )

                if normalized_params:
                    reasoning_request = self._apply_parameter_overrides(
                        reasoning_request, normalized_params
                    )
            except Exception as param_error:  # pragma: no cover - defensive
                logger.warning(
                    "Failed to apply URI parameters for reasoning phase (%s:%s): %s. Continuing without URI parameters.",
                    reasoning_backend,
                    reasoning_model,
                    param_error,
                )

        canonical_reasoning_request = self._prepare_backend_request(
            reasoning_request,
            target_model=f"{reasoning_backend}:{reasoning_model}",
            stream=True,
            messages=messages,
        )

        extra_body = getattr(canonical_reasoning_request, "extra_body", None)
        if isinstance(extra_body, dict):
            extra_body_keys = ", ".join(sorted(map(str, extra_body.keys())))
        elif extra_body is None:
            extra_body_keys = "None"
        else:
            extra_body_keys = f"<non-dict:{type(extra_body).__name__}>"

        logger.error(
            "[HYBRID DEBUG] Prepared reasoning request: model=%s, extra_body_keys=%s",
            canonical_reasoning_request.model,
            extra_body_keys,
        )

        try:
            from src.core.di.services import get_required_service
            from src.core.domain.request_context import (
                RequestContext,
                RequestCookies,
                RequestHeaders,
            )
            from src.core.services.backend_service import BackendService

            backend_service = get_required_service(BackendService)

            clean_context = RequestContext(
                headers=RequestHeaders(),
                cookies=RequestCookies(),
                state=None,
                app_state=None,
                session_id=None,
            )

            try:
                response = await asyncio.wait_for(
                    backend_service.call_completion(
                        canonical_reasoning_request,
                        stream=True,
                        allow_failover=False,
                        context=clean_context,
                    ),
                    timeout=REASONING_PHASE_TIMEOUT,
                )
            except TypeError as exc:
                if "context" not in str(exc):
                    raise
                response = await asyncio.wait_for(
                    backend_service.call_completion(
                        canonical_reasoning_request,
                        stream=True,
                        allow_failover=False,
                    ),
                    timeout=REASONING_PHASE_TIMEOUT,
                )

            response_media_type = getattr(response, "media_type", None)
            response_headers = getattr(response, "headers", None)

            if isinstance(response, StreamingResponseEnvelope) and response.content:
                stream = response.content
            else:
                logger.error(
                    "Reasoning model did not return streaming response",
                    extra={
                        "phase": "reasoning",
                        "reasoning_backend": reasoning_backend,
                        "reasoning_model": reasoning_model,
                        "response_type": type(response).__name__,
                    },
                )
                raise BackendError(
                    message="Reasoning model did not return streaming response",
                    code="reasoning_no_stream",
                    details={
                        "phase": "reasoning",
                        "reasoning_backend": reasoning_backend,
                        "reasoning_model": reasoning_model,
                        "response_type": type(response).__name__,
                    },
                )

            from src.connectors.utils.reasoning_stream_processor import (
                ReasoningStreamProcessor,
            )

            processor = ReasoningStreamProcessor()
            reasoning_text, reasoning_complete, metadata = (
                await processor.capture_reasoning_stream(stream)
            )
            tool_calls = metadata.get("tool_calls") or []
            raw_chunks = metadata.get("raw_chunks") or []

            if hasattr(response, "cancel_callback") and response.cancel_callback:
                try:
                    await response.cancel_callback()
                    logger.debug(
                        "Reasoning stream cancelled successfully",
                        extra={
                            "phase": "reasoning",
                            "reasoning_backend": reasoning_backend,
                            "reasoning_model": reasoning_model,
                        },
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug(
                        "Stream cancellation failed (non-fatal): %s",
                        exc,
                        extra={
                            "phase": "reasoning",
                            "reasoning_backend": reasoning_backend,
                            "reasoning_model": reasoning_model,
                            "error": str(exc),
                        },
                    )

            logger.info(
                "Reasoning phase complete: %s chars captured, method=%s, chunks=%s",
                len(reasoning_text),
                metadata.get("method"),
                metadata.get("chunks_processed"),
            )

            return ReasoningPhaseResult(
                text=reasoning_text,
                complete=reasoning_complete,
                tool_calls=tool_calls,
                raw_chunks=raw_chunks,
                media_type=response_media_type,
                headers=response_headers,
            )

        except ServiceResolutionError as exc:
            logger.error(
                "Failed to resolve BackendService for reasoning phase",
                extra={
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "error": str(exc),
                },
                exc_info=True,
            )
            raise BackendError(
                message=f"Failed to initialize reasoning backend: {exc}",
                code="reasoning_backend_init_failed",
                details={
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                },
            ) from exc

        except asyncio.TimeoutError as exc:
            logger.warning(
                "Reasoning phase timeout after %ss, attempting to use partial reasoning output",
                REASONING_PHASE_TIMEOUT,
                extra={
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "timeout_seconds": REASONING_PHASE_TIMEOUT,
                },
            )
            raise BackendError(
                message=f"Reasoning phase timeout after {REASONING_PHASE_TIMEOUT}s",
                code="reasoning_timeout",
                details={
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "timeout_seconds": REASONING_PHASE_TIMEOUT,
                },
            ) from exc

        except BackendError:
            raise

        except Exception as exc:
            logger.error(
                "Reasoning phase failed with unexpected error: %s",
                type(exc).__name__,
                extra={
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                exc_info=True,
            )
            raise BackendError(
                message=f"Reasoning phase failed: {exc}",
                code="reasoning_phase_failed",
                details={
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "error_type": type(exc).__name__,
                },
            ) from exc

    async def _execute_execution_phase(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        augmented_messages: list,
        execution_backend: str,
        execution_model: str,
        identity: IAppIdentityConfig | None,
        reasoning_output_length: int = 0,
        uri_params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute execution phase with augmented messages."""

        logger.info(
            "Starting execution phase with %s:%s",
            execution_backend,
            execution_model,
            extra={
                "phase": "execution",
                "execution_backend": execution_backend,
                "execution_model": execution_model,
                "reasoning_output_length": reasoning_output_length,
            },
        )

        if self._backend_registry is None:
            logger.error("Backend registry not initialized for execution phase")
            raise BackendError(
                message="Backend registry not initialized",
                code="backend_registry_not_initialized",
                details={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "reasoning_output_length": reasoning_output_length,
                },
            )

        try:
            from src.core.di.services import get_required_service
            from src.core.services.backend_factory import BackendFactory

            backend_factory_instance = get_required_service(BackendFactory)

            execution_backend_config = None
            if hasattr(self.config, "backends"):
                import contextlib

                with contextlib.suppress(AttributeError):
                    execution_backend_config = getattr(
                        self.config.backends, execution_backend
                    )

            execution_identity = self._resolve_backend_identity(
                execution_backend, identity, execution_backend_config
            )

            execution_connector = await backend_factory_instance.ensure_backend(
                execution_backend, self.config, execution_backend_config
            )

        except ValueError as exc:
            logger.error(
                "Execution backend '%s' not found in registry",
                execution_backend,
                extra={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "reasoning_output_length": reasoning_output_length,
                    "error": str(exc),
                },
            )
            raise BackendError(
                message=f"Execution backend '{execution_backend}' not found: {exc}",
                code="execution_backend_not_found",
                details={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "reasoning_output_length": reasoning_output_length,
                },
            ) from exc

        except Exception as exc:
            logger.error(
                "Failed to initialize execution backend '%s'",
                execution_backend,
                extra={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "reasoning_output_length": reasoning_output_length,
                    "error": str(exc),
                },
                exc_info=True,
            )
            raise BackendError(
                message=f"Failed to initialize execution backend: {exc}",
                code="execution_backend_init_failed",
                details={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "reasoning_output_length": reasoning_output_length,
                },
            ) from exc

        execution_preset_params = get_execution_params(execution_backend)
        execution_request = self._apply_reasoning_params(
            request_data, execution_preset_params
        )

        if uri_params:
            try:
                from src.core.services.uri_parameter_validator import (
                    URIParameterValidator,
                )

                validator = URIParameterValidator()
                normalized_params, validation_errors = validator.validate_and_normalize(
                    uri_params
                )

                if validation_errors:
                    logger.warning(
                        "URI parameter validation errors for execution phase (%s:%s): %s. Invalid parameters will be excluded.",
                        execution_backend,
                        execution_model,
                        ", ".join(validation_errors),
                    )

                if normalized_params:
                    execution_request = self._apply_parameter_overrides(
                        execution_request, normalized_params
                    )
            except Exception as param_error:  # pragma: no cover - defensive
                logger.warning(
                    "Failed to apply URI parameters for execution phase (%s:%s): %s. Continuing without URI parameters.",
                    execution_backend,
                    execution_model,
                    param_error,
                )

        try:
            response = await asyncio.wait_for(
                execution_connector.chat_completions(
                    request_data=execution_request,
                    processed_messages=augmented_messages,
                    effective_model=execution_model,
                    identity=execution_identity,
                    **kwargs,
                ),
                timeout=EXECUTION_PHASE_TIMEOUT,
            )

            logger.info(
                "Execution phase complete",
                extra={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                },
            )

            return response

        except asyncio.TimeoutError as exc:
            logger.error(
                "Execution phase timeout after %ss",
                EXECUTION_PHASE_TIMEOUT,
                extra={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "reasoning_output_length": reasoning_output_length,
                    "timeout_seconds": EXECUTION_PHASE_TIMEOUT,
                },
            )
            raise BackendError(
                message=f"Execution phase timeout after {EXECUTION_PHASE_TIMEOUT}s",
                code="execution_timeout",
                details={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "reasoning_output_length": reasoning_output_length,
                    "timeout_seconds": EXECUTION_PHASE_TIMEOUT,
                },
            ) from exc

        except BackendError:
            raise

        except Exception as exc:
            logger.error(
                "Execution phase failed with unexpected error: %s",
                type(exc).__name__,
                extra={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "reasoning_output_length": reasoning_output_length,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                exc_info=True,
            )
            raise BackendError(
                message=f"Execution phase failed: {exc}",
                code="execution_phase_failed",
                details={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "reasoning_output_length": reasoning_output_length,
                    "error_type": type(exc).__name__,
                },
            ) from exc
