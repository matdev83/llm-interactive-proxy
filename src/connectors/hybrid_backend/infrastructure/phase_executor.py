"""PhaseExecutor service for executing reasoning and execution phases.

This service extracts phase execution logic from HybridConnector to provide
focused, testable components for backend interaction.

Requirements satisfied:
- Req 9: Phase Executor Extraction
- NFR 4: Observability (entry/exit logging with timing)
"""

import asyncio
import logging
from dataclasses import asdict, is_dataclass
from typing import TYPE_CHECKING, Any, cast

import httpx

from src.connectors.hybrid_backend.infrastructure.identity_resolver import (
    IdentityResolver,
)
from src.connectors.hybrid_backend.models.phase_result import ReasoningPhaseResult
from src.connectors.hybrid_backend.protocols import IParameterApplicator
from src.connectors.utils.model_capabilities import (
    get_execution_params,
    get_reasoning_params,
)
from src.connectors.utils.reasoning_stream_processor import ReasoningStreamProcessor
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    ServiceResolutionError,
)
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatRequest
from src.core.domain.request_context import (
    RequestContext,
    RequestCookies,
    RequestHeaders,
)
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO

if TYPE_CHECKING:
    from src.core.services.backend_registry import BackendRegistry
    from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)


class PhaseExecutor:
    """Service for executing reasoning and execution phases via backends.

    This service encapsulates backend resolution, request preparation, and
    backend calls for both reasoning and execution phases.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        backend_registry: "BackendRegistry | None",
        parameter_applicator: IParameterApplicator,
        identity_resolver: IdentityResolver,
        translation_service: "TranslationService",
        connector_ref: Any | None = None,
    ) -> None:
        """Initialize PhaseExecutor.

        Args:
            client: HTTP client for API calls
            config: Application configuration
            backend_registry: Registry to resolve backend connectors
            parameter_applicator: Service for applying phase-specific parameters
            identity_resolver: Service for resolving identity configuration
            translation_service: Service for translating between formats
            connector_ref: Optional reference to HybridConnector for backward compatibility
        """
        self.client = client
        self.config = config
        self.backend_registry = backend_registry
        self.parameter_applicator = parameter_applicator
        self.identity_resolver = identity_resolver
        self.translation_service = translation_service
        self._connector_ref = connector_ref

    async def execute_reasoning_phase(
        self,
        messages: list[Any],
        reasoning_backend: str,
        reasoning_model: str,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        identity: IAppIdentityConfig | None,
        uri_params: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> ReasoningPhaseResult:
        """Execute reasoning phase and return captured output.

        Args:
            messages: Original message history
            reasoning_backend: Backend name for reasoning model
            reasoning_model: Model name for reasoning
            request_data: Original request data
            identity: Optional identity configuration
            uri_params: Optional URI parameter overrides
            session_id: Optional session identifier for tag scoping (requirement 8.2)

        Returns:
            Structured result containing reasoning text, tool calls, and stream metadata

        Raises:
            BackendError: If reasoning model call fails (HTTP 502)
        """
        import time

        start_time = time.time()
        logger.info(
            f"Starting reasoning phase with {reasoning_backend}:{reasoning_model}",
            extra={
                "phase": "reasoning",
                "reasoning_backend": reasoning_backend,
                "reasoning_model": reasoning_model,
            },
        )

        # Resolve reasoning backend connector from registry
        if self.backend_registry is None:
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

        # Create request payload for reasoning model
        reasoning_preset_params = dict(get_reasoning_params(reasoning_backend))
        reasoning_request = self.parameter_applicator.apply_reasoning_params(
            request_data, reasoning_backend, reasoning_preset_params
        )

        # Apply URI parameters if provided
        if uri_params:
            try:
                # Validate URI parameters before applying
                from src.core.services.uri_parameter_validator import (
                    URIParameterValidator,
                )

                validator = URIParameterValidator()
                normalized_params, validation_errors = validator.validate_and_normalize(
                    uri_params
                )

                if validation_errors:
                    logger.warning(
                        f"URI parameter validation errors for reasoning phase ({reasoning_backend}:{reasoning_model}): "
                        f"{', '.join(validation_errors)}. Invalid parameters will be excluded.",
                        extra={
                            "phase": "reasoning",
                            "reasoning_backend": reasoning_backend,
                            "reasoning_model": reasoning_model,
                            "validation_errors": validation_errors,
                        },
                    )

                # Apply normalized parameters
                if normalized_params:
                    # Apply via reasoning params with overrides (method handles merging)
                    reasoning_request = (
                        self.parameter_applicator.apply_reasoning_params(
                            reasoning_request, reasoning_backend, normalized_params
                        )
                    )
            except Exception as param_error:
                # Log error but continue without URI parameters
                logger.warning(
                    f"Failed to apply URI parameters for reasoning phase ({reasoning_backend}:{reasoning_model}): "
                    f"{param_error}. Continuing without URI parameters.",
                    extra={
                        "phase": "reasoning",
                        "reasoning_backend": reasoning_backend,
                        "reasoning_model": reasoning_model,
                        "error": str(param_error),
                    },
                    exc_info=True,
                )

        # Prepare canonical request for backend service
        # Use full backend:model format so backend_service can properly resolve it
        canonical_reasoning_request = self._prepare_backend_request(
            reasoning_request,
            target_model=f"{reasoning_backend}:{reasoning_model}",
            stream=True,
            messages=messages,
        )

        # DEBUG: Log what we're sending
        extra_body = getattr(canonical_reasoning_request, "extra_body", None)
        if isinstance(extra_body, dict):
            extra_body_keys = ", ".join(sorted(map(str, extra_body.keys())))
        elif extra_body is None:
            extra_body_keys = "None"
        else:
            extra_body_keys = f"<non-dict:{type(extra_body).__name__}>"

        logger.debug(
            "[HYBRID DEBUG] Prepared reasoning request: model=%s, extra_body_keys=%s",
            canonical_reasoning_request.model,
            extra_body_keys,
            extra={
                "phase": "reasoning",
                "reasoning_backend": reasoning_backend,
                "reasoning_model": reasoning_model,
            },
        )

        try:
            from src.core.di.services import get_required_service
            from src.core.services.backend_service import BackendService

            backend_service = get_required_service(BackendService)

            # Extract session_id from identity if not provided (requirement 8.2: reuse session_id across calls)
            if session_id is None and identity is not None:
                session_id = getattr(identity, "session_id", None)

            # Create context with session_id for non-forwardable enforcement (requirement 8.1, 8.2)
            # Note: We still prevent session backend inheritance by not passing session in extra_body
            # The session_id is used only for non-forwardable tag scoping, not backend selection
            clean_context = RequestContext(
                headers=RequestHeaders(),
                cookies=RequestCookies(),
                state=None,
                app_state=None,
                session_id=session_id,  # Set session_id for tag scoping (requirement 8.2)
            )

            # Call reasoning model with timeout via backend service
            try:
                response = await asyncio.wait_for(
                    backend_service.call_completion(
                        canonical_reasoning_request,
                        stream=True,
                        allow_failover=False,
                        context=clean_context,  # Prefer context-enabled call
                    ),
                    timeout=self.config.backends.hybrid_reasoning_model_timeout,
                )
            except TypeError as exc:
                # Integration stubs may not accept context; retry without it.
                if "context" not in str(exc):
                    raise
                response = await asyncio.wait_for(
                    backend_service.call_completion(
                        canonical_reasoning_request,
                        stream=True,
                        allow_failover=False,
                    ),
                    timeout=self.config.backends.hybrid_reasoning_model_timeout,
                )

            # Extract stream from response
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

            # Use ReasoningStreamProcessor to capture reasoning output
            processor = ReasoningStreamProcessor()
            capture_result = await processor.capture_reasoning_stream(stream)
            reasoning_text = capture_result.reasoning_text
            reasoning_complete = capture_result.reasoning_complete
            metadata = capture_result.metadata
            tool_calls = metadata.tool_calls
            raw_chunks = metadata.raw_chunks

            # Cancel the stream if it has a cancel callback
            if hasattr(response, "cancel_callback") and response.cancel_callback:
                try:
                    await response.cancel_callback()
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug("Reasoning stream cancelled successfully")
                except Exception as e:
                    logger.warning(
                        "Error cancelling reasoning stream: %s",
                        e,
                        extra={
                            "phase": "reasoning",
                            "reasoning_backend": reasoning_backend,
                            "reasoning_model": reasoning_model,
                            "error": str(e),
                        },
                        exc_info=True,
                    )

            elapsed_time = time.time() - start_time
            logger.info(
                f"Reasoning phase complete: {len(reasoning_text)} chars captured, "
                f"method={metadata.method}, "
                f"chunks={metadata.chunks_processed}, "
                f"elapsed={elapsed_time:.2f}s",
                extra={
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "chars_captured": len(reasoning_text),
                    "chunks_processed": metadata.chunks_processed,
                    "elapsed_seconds": elapsed_time,
                },
            )

            return ReasoningPhaseResult(
                text=reasoning_text,
                complete=reasoning_complete,
                tool_calls=tool_calls,
                raw_chunks=raw_chunks,
                media_type=response_media_type,
                headers=response_headers,
            )

        except ServiceResolutionError as e:
            logger.error(
                "Failed to resolve BackendService for reasoning phase",
                extra={
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "error": str(e),
                },
                exc_info=True,
            )
            raise BackendError(
                message=f"Failed to initialize reasoning backend: {e}",
                code="reasoning_backend_init_failed",
                details={
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                },
            ) from e

        except asyncio.TimeoutError:
            elapsed_time = time.time() - start_time
            logger.warning(
                f"Reasoning phase timed out after {self.config.backends.hybrid_reasoning_model_timeout}s. "
                "Proceeding without reasoning model output.",
                extra={
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "timeout_seconds": self.config.backends.hybrid_reasoning_model_timeout,
                    "elapsed_seconds": elapsed_time,
                },
                exc_info=True,
            )
            return ReasoningPhaseResult(
                text="",
                complete=False,
                tool_calls=[],
                raw_chunks=[],
                media_type=None,
                headers=None,
            )
        except BackendError:
            # Re-raise BackendError as-is (already has proper context)
            raise
        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error(
                f"Reasoning phase failed with unexpected error: {type(e).__name__}",
                extra={
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "error_type": type(e).__name__,
                    "error": str(e),
                    "elapsed_seconds": elapsed_time,
                },
                exc_info=True,
            )
            raise BackendError(
                message=f"Reasoning phase failed: {e}",
                code="reasoning_phase_failed",
                details={
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "error_type": type(e).__name__,
                },
            ) from e

    def _prepare_backend_request(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        target_model: str,
        stream: bool,
        messages: list | None = None,
    ) -> CanonicalChatRequest:
        """Normalize request for backend service calls.

        Args:
            request_data: Request data in various formats
            target_model: Target model name (backend:model format)
            stream: Whether to stream the response
            messages: Optional message list to override

        Returns:
            CanonicalChatRequest ready for backend service

        Raises:
            TypeError: If request_data format is unsupported
        """
        # Check if HybridConnector's _prepare_backend_request is patched
        # This allows tests to patch the method and verify model format
        if (
            self._connector_ref
            and hasattr(self._connector_ref, "_prepare_backend_request")
            and callable(self._connector_ref._prepare_backend_request)
        ):
            # Always use connector's method if available (wrapper handles patching)
            result = self._connector_ref._prepare_backend_request(
                request_data=request_data,
                target_model=target_model,
                stream=stream,
                messages=messages,
            )
            # Ensure result is CanonicalChatRequest
            if not isinstance(result, CanonicalChatRequest):
                result = self.translation_service.to_domain_request(result, "openai")
            # Type narrowing: result is now guaranteed to be CanonicalChatRequest
            return cast(CanonicalChatRequest, result)

        # Normal path: use internal implementation
        request_obj: Any = request_data

        if hasattr(request_obj, "model_copy"):
            request_obj = request_obj.model_copy(
                update={"model": target_model, "stream": stream}
            )
        elif isinstance(request_obj, dict):
            request_dict = dict(request_obj)
            request_dict["model"] = target_model
            request_dict["stream"] = stream
            request_obj = self.translation_service.to_domain_request(
                request_dict, "openai"
            )
        elif is_dataclass(request_obj) and not isinstance(request_obj, type):
            request_dict = asdict(request_obj)
            request_dict["model"] = target_model
            request_dict["stream"] = stream
            request_obj = self.translation_service.to_domain_request(
                request_dict, "openai"
            )
        elif isinstance(request_obj, ChatRequest):
            request_obj = request_obj.model_copy(
                update={"model": target_model, "stream": stream}
            )
        else:
            raise TypeError(
                "Unable to prepare backend request from type "
                f"{type(request_obj).__name__}"
            )

        if not isinstance(request_obj, CanonicalChatRequest):
            request_obj = self.translation_service.to_domain_request(
                request_obj, "openai"
            )

        if messages is not None:
            request_obj = request_obj.model_copy(update={"messages": messages})

        # Remove session_id from extra_body to prevent session backend inheritance
        # This ensures the backend is resolved from the model name, not session state
        if request_obj.extra_body and isinstance(request_obj.extra_body, dict):
            keys_to_strip = {"session_id", "backend_type", "model"}
            cleaned_extra_body = {
                k: v
                for k, v in request_obj.extra_body.items()
                if k not in keys_to_strip
            }
            if len(cleaned_extra_body) != len(request_obj.extra_body):
                request_obj = request_obj.model_copy(
                    update={
                        "extra_body": cleaned_extra_body if cleaned_extra_body else None
                    }
                )

        return cast(CanonicalChatRequest, request_obj)

    async def execute_execution_phase(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        augmented_messages: list[Any],
        execution_backend: str,
        execution_model: str,
        identity: IAppIdentityConfig | None,
        uri_params: dict[str, Any] | None = None,
        session_id: str | None = None,
        original_message_count: int | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute execution phase with augmented messages.

        Args:
            request_data: Original request data
            augmented_messages: Messages with reasoning appended
            execution_backend: Backend name for execution
            execution_model: Model name for execution
            identity: Optional identity configuration
            uri_params: Optional URI parameter overrides
            session_id: Optional session identifier for enforcement boundary
            original_message_count: Optional count of original messages before augmentation (for injection boundary)
            **kwargs: Additional arguments

        Returns:
            Response from execution model

        Raises:
            BackendError: If execution model call fails (HTTP 502)
        """
        import time

        start_time = time.time()
        logger.info(
            f"Starting execution phase with {execution_backend}:{execution_model}",
            extra={
                "phase": "execution",
                "execution_backend": execution_backend,
                "execution_model": execution_model,
            },
        )

        # Resolve execution backend connector from registry
        if self.backend_registry is None:
            logger.error("Backend registry not initialized for execution phase")
            raise BackendError(
                message="Backend registry not initialized",
                code="backend_registry_not_initialized",
                details={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                },
            )

        # Extract session_id from identity if not provided
        if session_id is None and identity is not None:
            session_id = getattr(identity, "session_id", None)

        # Create request payload with augmented messages
        execution_preset_params = dict(get_execution_params(execution_backend))
        execution_request = self.parameter_applicator.apply_execution_params(
            request_data, execution_backend, execution_preset_params
        )

        # Apply URI parameters if provided
        if uri_params:
            try:
                # Validate URI parameters before applying
                from src.core.services.uri_parameter_validator import (
                    URIParameterValidator,
                )

                validator = URIParameterValidator()
                normalized_params, validation_errors = validator.validate_and_normalize(
                    uri_params
                )

                if validation_errors:
                    logger.warning(
                        f"URI parameter validation errors for execution phase ({execution_backend}:{execution_model}): "
                        f"{', '.join(validation_errors)}. Invalid parameters will be excluded.",
                        extra={
                            "phase": "execution",
                            "execution_backend": execution_backend,
                            "execution_model": execution_model,
                            "validation_errors": validation_errors,
                        },
                    )

                # Apply normalized parameters
                if normalized_params:
                    # Apply via execution params with overrides (method handles merging)
                    execution_request = (
                        self.parameter_applicator.apply_execution_params(
                            execution_request, execution_backend, normalized_params
                        )
                    )
            except Exception as param_error:
                # Log error but continue without URI parameters
                logger.warning(
                    f"Failed to apply URI parameters for execution phase ({execution_backend}:{execution_model}): "
                    f"{param_error}. Continuing without URI parameters.",
                    extra={
                        "phase": "execution",
                        "execution_backend": execution_backend,
                        "execution_model": execution_model,
                        "error": str(param_error),
                    },
                    exc_info=True,
                )

        try:
            # Prepare canonical request for backend service
            # Respect the original request's stream flag if provided
            original_stream = getattr(execution_request, "stream", False)
            if isinstance(request_data, dict):
                original_stream = request_data.get("stream", original_stream)
            canonical_execution_request = self._prepare_backend_request(
                execution_request,
                target_model=f"{execution_backend}:{execution_model}",
                stream=original_stream,  # Respect original request's stream flag
                messages=augmented_messages,
            )

            # Get BackendService from DI
            from src.core.di.services import get_required_service
            from src.core.services.backend_service import BackendService

            backend_service = get_required_service(BackendService)

            # Create RequestContext with session_id and injection provenance boundary
            # If original_message_count is provided, set the injection boundary
            from pydantic.types import JsonValue

            context_extensions: dict[str, JsonValue] = {}
            if original_message_count is not None and original_message_count < len(
                augmented_messages
            ):
                from src.core.services.non_forwardable_message_enforcer import (
                    PROXY_INJECTED_MESSAGES_START_INDEX_KEY,
                )

                context_extensions[PROXY_INJECTED_MESSAGES_START_INDEX_KEY] = (
                    original_message_count
                )

            context = RequestContext(
                headers=RequestHeaders(),
                cookies=RequestCookies(),
                state=None,
                app_state=None,
                session_id=session_id,
                extensions=context_extensions if context_extensions else {},
            )

            # Call execution model with timeout via backend service (ensures non-forwardable enforcement)
            # Use the stream flag from the canonical request
            execution_stream = getattr(canonical_execution_request, "stream", False)
            response = await asyncio.wait_for(
                backend_service.call_completion(
                    request=canonical_execution_request,
                    stream=execution_stream,
                    allow_failover=False,
                    context=context,
                ),
                timeout=self.config.backends.hybrid_execution_model_timeout,
            )

            elapsed_time = time.time() - start_time
            logger.info(
                "Execution phase complete",
                extra={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "elapsed_seconds": elapsed_time,
                },
            )

            return response

        except asyncio.TimeoutError as e:
            elapsed_time = time.time() - start_time
            # Handle execution timeout
            logger.error(
                f"Execution phase timeout after {self.config.backends.hybrid_execution_model_timeout}s",
                extra={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "timeout_seconds": self.config.backends.hybrid_execution_model_timeout,
                    "elapsed_seconds": elapsed_time,
                },
                exc_info=True,
            )
            raise BackendError(
                message=f"Execution phase timeout after {self.config.backends.hybrid_execution_model_timeout}s",
                code="execution_timeout",
                details={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "timeout_seconds": self.config.backends.hybrid_execution_model_timeout,
                },
            ) from e

        except BackendError:
            # Re-raise BackendError as-is (already has proper context)
            raise
        except AuthenticationError:
            # Re-raise AuthenticationError as-is (already has proper context)
            raise
        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error(
                f"Execution phase failed with unexpected error: {type(e).__name__}",
                extra={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "error_type": type(e).__name__,
                    "error": str(e),
                    "elapsed_seconds": elapsed_time,
                },
                exc_info=True,
            )
            raise BackendError(
                message=f"Execution phase failed: {e}",
                code="execution_phase_failed",
                details={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "error_type": type(e).__name__,
                },
            ) from e
