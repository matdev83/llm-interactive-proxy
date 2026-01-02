"""HybridOrchestrator service for coordinating two-phase hybrid completion flow.

This service extracts orchestration logic from HybridConnector to provide
focused, testable components for flow coordination.

Requirements satisfied:
- Req 7: Orchestrator Extraction
- NFR 4: Observability (logging with timing)
"""

import logging
import time
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from src.core.config.app_config import AppConfig
    from src.core.interfaces.configuration_interface import IAppIdentityConfig

from src.connectors.hybrid_backend.models.phase_result import ReasoningPhaseResult
from src.connectors.hybrid_backend.protocols import (
    IInjectionPolicy,
    IMessageAugmentor,
    IModelSpecParser,
    IParameterApplicator,
    IPhaseExecutor,
    IReasoningMarkupProcessor,
    IResponseBuilder,
    IResponseFilter,
)
from src.core.common.exceptions import (
    BackendError,
    ConfigurationError,
    InvalidRequestError,
)
from src.core.domain.chat import CanonicalChatRequest, ChatRequest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.services.boundary_validation import log_boundary_validation_failure

logger = logging.getLogger(__name__)


class HybridOrchestrator:
    """Service for coordinating the two-phase hybrid completion flow.

    This service orchestrates the complete flow: parse model spec, evaluate
    injection policy, execute reasoning phase (if needed), augment messages,
    execute execution phase, filter response, and build final response.
    """

    def __init__(
        self,
        model_spec_parser: IModelSpecParser,
        parameter_applicator: IParameterApplicator,
        injection_policy: IInjectionPolicy,
        phase_executor: IPhaseExecutor,
        message_augmentor: IMessageAugmentor,
        response_filter: IResponseFilter,
        response_builder: IResponseBuilder,
        config: "AppConfig",
        reasoning_markup_processor: IReasoningMarkupProcessor,
        connector: Any = None,
    ) -> None:
        """Initialize HybridOrchestrator.

        Args:
            model_spec_parser: Service for parsing model specifications
            parameter_applicator: Service for applying phase parameters
            injection_policy: Service for injection decisions
            phase_executor: Service for executing phases
            message_augmentor: Service for augmenting messages
            response_filter: Service for filtering responses
            response_builder: Service for building responses
            config: Application configuration
            reasoning_markup_processor: Markup processor for tag normalization (Req 4.1)
            connector: Optional connector instance for backward-compatible test patching
        """
        self.model_spec_parser = model_spec_parser
        self.parameter_applicator = parameter_applicator
        self.injection_policy = injection_policy
        self.phase_executor = phase_executor
        self.message_augmentor = message_augmentor
        self.response_filter = response_filter
        self.response_builder = response_builder
        self.config = config
        self._reasoning_markup_processor = reasoning_markup_processor
        self._connector = connector

    async def execute(
        self,
        request_data: CanonicalChatRequest | ChatRequest,
        processed_messages: list[Any],
        effective_model: str,
        identity: "IAppIdentityConfig | None" = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute the complete two-phase hybrid completion.

        Boundary Hardening (Requirement 5.2):
            This method enforces typed contract boundaries by rejecting dict inputs.
            Dict-to-contract coercion must occur at explicit adapter boundaries (transport
            adapters, connector invoker) before reaching this core orchestration service.
            This ensures a single canonical representation per concept throughout the
            core pipeline (Requirement 5.3).

        Args:
            request_data: Original request (canonical contract only - CanonicalChatRequest
                or ChatRequest). Dict inputs are rejected with InvalidRequestError.
            processed_messages: Messages after command processing
            effective_model: Format "hybrid:[backend:model,backend:model]"
            identity: Optional identity configuration
            **kwargs: Additional arguments

        Returns:
            Response envelope (streaming or non-streaming) with execution model's response

        Raises:
            InvalidRequestError: If request_data is a dict. Dict-to-domain coercion is
                centralized at adapter boundaries (transport adapters, connector invoker).
                Expected CanonicalChatRequest or ChatRequest.
            ValueError: If model specification is invalid
            ConfigurationError: If hybrid backend is disabled
            BackendError: If either phase fails (HTTP 502)
        """
        # BOUNDARY HARDENING: Reject dict input - coercion should be centralized at adapter boundaries
        if isinstance(request_data, dict):
            # Extract correlation identifiers from available sources
            # HybridOrchestrator doesn't have RequestContext, but can extract session_id from identity
            session_id = getattr(identity, "session_id", None) if identity else None
            correlation_ids = {"request_id": None, "session_id": session_id}

            # Log boundary validation failure with available correlation identifiers
            log_boundary_validation_failure(
                logger=logger,
                message="HybridOrchestrator received dict input. "
                "Dict-to-domain coercion is centralized at adapter boundaries (transport adapters, connector invoker). "
                "Expected CanonicalChatRequest or ChatRequest.",
                context=None,  # No RequestContext available, but we log session_id from identity
                service="HybridOrchestrator",
                violation_type="dict_input",
                details={
                    "received_type": "dict",
                    "expected_type": "CanonicalChatRequest | ChatRequest",
                    "session_id": correlation_ids["session_id"],  # Include in details for visibility
                },
            )

            raise InvalidRequestError(
                message="HybridOrchestrator received dict input. "
                "Dict-to-domain coercion is centralized at adapter boundaries (transport adapters, connector invoker). "
                "Expected CanonicalChatRequest or ChatRequest.",
                details={
                    "received_type": "dict",
                    "service": "HybridOrchestrator",
                },
            )
        start_time = time.time()
        session_id = getattr(identity, "session_id", None) if identity else None

        # Ensure session_id exists for requirement 8.1 and 8.2 (reuse across phases)
        # Generate one if missing to ensure consistency across reasoning and execution phases
        if session_id is None:
            from uuid import uuid4

            session_id = str(uuid4())
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Generated session ID for hybrid backend interaction: %s",
                    session_id,
                )

        # Check if hybrid backend is disabled
        self._check_hybrid_backend_enabled(session_id)

        # Prepare execution context: parse spec, validate params, evaluate injection
        request_dict, spec, reasoning_params, execution_params, injection_decision = (
            self._prepare_execution_context(
                request_data, effective_model, processed_messages, identity, session_id
            )
        )

        # Initialize reasoning state
        reasoning_output, client_reasoning, reasoning_time = "", "", 0.0
        reasoning_result = None

        # Execute reasoning phase if injection is enabled
        if injection_decision.should_inject:
            reasoning_result, reasoning_output, client_reasoning, reasoning_time = (
                await self._execute_reasoning_with_backoff(
                    processed_messages,
                    spec.reasoning_backend,
                    spec.reasoning_model,
                    request_data,
                    identity,
                    reasoning_params,
                    session_id,
                    start_time,
                )
            )
            # Check for tool-call-only short-circuit (Req 7.5)
            short_circuit = self._check_tool_call_short_circuit(
                reasoning_result, client_reasoning, request_dict, spec, session_id
            )
            if short_circuit:
                return short_circuit

        # Augment messages with reasoning and execute execution phase
        augmented_messages = self.message_augmentor.augment(
            messages=processed_messages,
            reasoning_output=reasoning_output,
            execution_backend=spec.execution_backend,
        )

        response = await self._execute_execution_phase_with_fallback(
            request_data,
            augmented_messages,
            spec.execution_backend,
            spec.execution_model,
            identity,
            execution_params,
            session_id,
            reasoning_output,
            original_message_count=len(processed_messages),
            **kwargs,
        )

        # Filter and build final response
        return await self._filter_and_build_response(
            response,
            reasoning_output,
            client_reasoning,
            spec.reasoning_backend,
            spec.reasoning_model,
            session_id,
            start_time,
            reasoning_time,
        )

    def _prepare_execution_context(
        self,
        request_data: CanonicalChatRequest | ChatRequest,
        effective_model: str,
        processed_messages: list[Any],
        identity: "IAppIdentityConfig | None",
        session_id: str | None,
    ) -> tuple[dict[str, Any], Any, dict[str, Any], dict[str, Any], Any]:
        """Prepare execution context: parse spec, validate params, evaluate injection.

        Args:
            request_data: Canonical request contract (never a dict)
            effective_model: Model specification string
            processed_messages: Processed messages list
            identity: Optional identity configuration
            session_id: Optional session identifier

        Returns:
            Tuple of (request_dict, spec, reasoning_params, execution_params, injection_decision)
            Note: request_dict is converted from canonical contract for internal use only
        """
        # Convert canonical contract to dict for internal use (injection policy, etc.)
        # This is an internal conversion, not accepting dicts at the boundary
        request_dict = self._canonical_request_to_dict(request_data)
        spec = self.model_spec_parser.parse(effective_model)

        # Validate and clean parameters
        reasoning_params, execution_params = self._validate_and_clean_params(
            spec.reasoning_params, spec.execution_params, session_id, spec
        )

        # Evaluate injection policy
        probability_override = self._extract_probability_override(request_data)
        raw_messages = request_dict.get("messages")
        request_messages = raw_messages if isinstance(raw_messages, list) else None
        injection_decision = self.injection_policy.should_inject(
            processed_messages=processed_messages,
            request_messages=request_messages,
            probability_override=probability_override,
            identity=identity,
        )

        return (
            request_dict,
            spec,
            reasoning_params,
            execution_params,
            injection_decision,
        )

    def _check_hybrid_backend_enabled(self, session_id: str | None) -> None:
        """Check if hybrid backend is disabled and raise error if so."""
        if (
            hasattr(self.config, "backends")
            and hasattr(self.config.backends, "disable_hybrid_backend")
            and self.config.backends.disable_hybrid_backend
        ):
            logger.warning(
                "Hybrid backend request rejected - backend is disabled",
                extra={"session_id": session_id},
            )
            raise ConfigurationError(
                message="Hybrid backend is disabled",
                code="hybrid_backend_disabled",
            )

    def _check_tool_call_short_circuit(
        self,
        reasoning_result: ReasoningPhaseResult | None,
        client_reasoning: str,
        request_dict: dict[str, Any],
        spec: Any,
        session_id: str | None,
    ) -> ResponseEnvelope | StreamingResponseEnvelope | None:
        """Check for tool-call-only short-circuit condition and return response if applicable."""
        if (
            reasoning_result
            and not client_reasoning
            and reasoning_result.has_tool_calls()
        ):
            logger.info(
                "[hybrid-backend] Skipping execution model - reasoning produced tool calls without content",
                extra={
                    "session_id": session_id,
                    "reasoning_backend": spec.reasoning_backend,
                    "reasoning_model": spec.reasoning_model,
                    "tool_call_count": len(reasoning_result.tool_calls),
                },
            )
            return self.response_builder.build_tool_call_response(
                tool_calls=reasoning_result.tool_calls,
                request_dict=request_dict,
                backend=spec.reasoning_backend,
                model=spec.reasoning_model,
            )
        return None

    async def _execute_execution_phase_with_fallback(
        self,
        request_data: CanonicalChatRequest | ChatRequest,
        augmented_messages: list[Any],
        execution_backend: str,
        execution_model: str,
        identity: "IAppIdentityConfig | None",
        execution_params: dict[str, Any],
        session_id: str | None,
        reasoning_output: str,
        original_message_count: int | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute execution phase with connector fallback for test compatibility."""
        try:
            # Check if connector has patched methods (for test backward compatibility)
            if (
                self._connector
                and hasattr(self._connector, "_execute_execution_phase")
                and callable(self._connector._execute_execution_phase)
            ):
                result = await self._connector._execute_execution_phase(  # type: ignore[misc]
                    request_data=request_data,
                    augmented_messages=augmented_messages,
                    execution_backend=execution_backend,
                    execution_model=execution_model,
                    identity=identity,
                    uri_params=execution_params,
                    **kwargs,
                )
                return cast(ResponseEnvelope | StreamingResponseEnvelope, result)
            return await self.phase_executor.execute_execution_phase(
                request_data=request_data,
                augmented_messages=augmented_messages,
                execution_backend=execution_backend,
                execution_model=execution_model,
                identity=identity,
                uri_params=execution_params,
                session_id=session_id,
                original_message_count=original_message_count,
                **kwargs,
            )
        except BackendError as e:
            logger.error(
                f"Execution phase failed: {e.message}",
                extra={
                    "session_id": session_id,
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "reasoning_output_length": len(reasoning_output),
                    "error_code": e.code,
                    "error": e.message,
                },
                exc_info=True,
            )
            raise BackendError(
                message=f"Hybrid backend error (execution phase): {e.message}",
                code="hybrid_execution_failed",
                details={
                    "phase": "execution",
                    "execution_backend": execution_backend,
                    "execution_model": execution_model,
                    "reasoning_output_length": len(reasoning_output),
                    "original_error": e.code,
                },
            ) from e

    def _canonical_request_to_dict(
        self, request_data: CanonicalChatRequest | ChatRequest
    ) -> dict[str, Any]:
        """Convert canonical request contract to dict format for internal use.

        This is an internal conversion method that only accepts canonical contracts.
        Dict-to-contract coercion must happen at adapter boundaries, not here.

        Args:
            request_data: Canonical request contract (CanonicalChatRequest or ChatRequest)

        Returns:
            Dictionary representation of the request for internal use

        Raises:
            TypeError: If request_data is a dict (runtime check for defensive programming)
        """
        # Runtime check: reject dicts even though type signature doesn't allow them
        # This is defensive programming since Python doesn't enforce type hints at runtime
        if isinstance(request_data, dict):
            raise TypeError(
                "request_data must be CanonicalChatRequest or ChatRequest, "
                "but got dict. Dict-to-contract coercion must happen at adapter boundaries."
            )
        # Type signature guarantees request_data is CanonicalChatRequest | ChatRequest
        # Both are Pydantic models with model_dump() method
        return request_data.model_dump()

    def _validate_and_clean_params(
        self,
        reasoning_params: dict[str, Any],
        execution_params: dict[str, Any],
        session_id: str | None,
        spec: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Validate reasoning backend and clean reasoning_effort parameters."""
        # Validate reasoning backend compatibility
        if spec.reasoning_backend in {
            "gemini-oauth-plan",
            "gemini-oauth-free",
            "antigravity-oauth",
        }:
            raise BackendError(
                message=f"Backend '{spec.reasoning_backend}' does not support reasoning tags and cannot be used for the reasoning phase.",
                code="incompatible_reasoning_backend",
                details={
                    "reasoning_backend": spec.reasoning_backend,
                    "reasoning_model": spec.reasoning_model,
                },
            )

        # Check for reasoning_effort parameter and log warning
        has_reasoning_effort_in_reasoning = "reasoning_effort" in reasoning_params
        has_reasoning_effort_in_execution = "reasoning_effort" in execution_params

        if has_reasoning_effort_in_reasoning or has_reasoning_effort_in_execution:
            logger.warning(
                "reasoning_effort parameter in hybrid model string is not effective. "
                "Hybrid backend enforces reasoning effort by design.",
                extra={
                    "session_id": session_id,
                    "reasoning_backend": spec.reasoning_backend,
                    "reasoning_model": spec.reasoning_model,
                    "execution_backend": spec.execution_backend,
                    "execution_model": spec.execution_model,
                    "reasoning_effort_in_reasoning": has_reasoning_effort_in_reasoning,
                    "reasoning_effort_in_execution": has_reasoning_effort_in_execution,
                },
            )

            # Remove reasoning_effort from parameters
            if has_reasoning_effort_in_reasoning:
                reasoning_params = {
                    k: v for k, v in reasoning_params.items() if k != "reasoning_effort"
                }
            if has_reasoning_effort_in_execution:
                execution_params = {
                    k: v for k, v in execution_params.items() if k != "reasoning_effort"
                }

        return reasoning_params, execution_params

    def _extract_probability_override(
        self, request_data: CanonicalChatRequest | ChatRequest
    ) -> float | None:
        """Extract probability override from request_data.extra_body.

        Args:
            request_data: Canonical request contract (never a dict)

        Returns:
            Probability override value or None
        """
        extra_body = getattr(request_data, "extra_body", {})
        if extra_body is None:
            extra_body = {}

        temp_prob_override = extra_body.get("_temp_hybrid_reasoning_probability")
        if temp_prob_override is not None:
            return float(temp_prob_override)
        return None

    async def _execute_reasoning_with_backoff(
        self,
        processed_messages: list[Any],
        reasoning_backend: str,
        reasoning_model: str,
        request_data: CanonicalChatRequest | ChatRequest,
        identity: "IAppIdentityConfig | None",
        reasoning_params: dict[str, Any],
        session_id: str | None,
        start_time: float,
    ) -> tuple[ReasoningPhaseResult, str, str, float]:
        """Execute reasoning phase and handle backoff updates."""
        try:
            # Check if connector has patched methods (for test backward compatibility)
            if (
                self._connector
                and hasattr(self._connector, "_execute_reasoning_phase")
                and callable(self._connector._execute_reasoning_phase)
            ):
                reasoning_result = await self._connector._execute_reasoning_phase(  # type: ignore[misc]
                    messages=processed_messages,
                    reasoning_backend=reasoning_backend,
                    reasoning_model=reasoning_model,
                    request_data=request_data,
                    identity=identity,
                    uri_params=reasoning_params,
                    session_id=session_id,  # Pass session_id for tag scoping (requirement 8.2)
                )
            else:
                reasoning_result = await self.phase_executor.execute_reasoning_phase(
                    messages=processed_messages,
                    reasoning_backend=reasoning_backend,
                    reasoning_model=reasoning_model,
                    request_data=request_data,
                    identity=identity,
                    uri_params=reasoning_params,
                    session_id=session_id,  # Pass session_id for tag scoping (requirement 8.2)
                )

            reasoning_output = reasoning_result.text
            reasoning_time = time.time() - start_time

            # Format reasoning for client (plain text)
            # Use injected markup processor (strict dependency inversion - Req 4)
            reasoning_text = self._reasoning_markup_processor.normalize(
                reasoning_output, reasoning_backend
            )
            client_reasoning = reasoning_text.plain

            # Check if reasoning has content
            has_reasoning_content = bool(client_reasoning)
            if not has_reasoning_content:
                client_reasoning = ""

            # Log reasoning phase completion
            logger.info(
                f"Reasoning phase completed: {len(reasoning_output)} chars captured in {reasoning_time:.2f}s",
                extra={
                    "session_id": session_id,
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "output_length": len(reasoning_output),
                    "duration_seconds": reasoning_time,
                    "tool_call_count": len(reasoning_result.tool_calls),
                },
            )

            # Update backoff based on latency threshold
            latency_threshold = getattr(
                self.config.backends, "hybrid_reasoning_latency_threshold", 0.0
            )
            backoff_turns = getattr(
                self.config.backends, "hybrid_reasoning_backoff_turns", 0
            )
            if (
                latency_threshold
                and latency_threshold > 0
                and backoff_turns
                and backoff_turns > 0
                and reasoning_time > latency_threshold
            ):
                self.injection_policy.update_backoff(success=False)
                logger.warning(
                    "Reasoning latency %.2fs exceeded threshold %.2fs; activating adaptive backoff for %s turn(s)",
                    reasoning_time,
                    latency_threshold,
                    backoff_turns,
                    extra={
                        "session_id": session_id,
                        "phase": "reasoning",
                        "reasoning_backend": reasoning_backend,
                        "reasoning_model": reasoning_model,
                        "reasoning_latency": reasoning_time,
                        "latency_threshold": latency_threshold,
                        "backoff_turns": backoff_turns,
                    },
                )
            else:
                self.injection_policy.update_backoff(success=True)

            return reasoning_result, reasoning_output, client_reasoning, reasoning_time

        except BackendError as e:
            logger.error(
                f"Reasoning phase failed: {e.message}",
                extra={
                    "session_id": session_id,
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "error_code": e.code,
                    "error": e.message,
                },
                exc_info=True,
            )
            raise BackendError(
                message=f"Hybrid backend error (reasoning phase): {e.message}",
                code="hybrid_reasoning_failed",
                details={
                    "phase": "reasoning",
                    "reasoning_backend": reasoning_backend,
                    "reasoning_model": reasoning_model,
                    "original_error": e.code,
                },
            ) from e

    async def _filter_and_build_response(
        self,
        response: ResponseEnvelope | StreamingResponseEnvelope,
        reasoning_output: str,
        client_reasoning: str,
        reasoning_backend: str,
        reasoning_model: str,
        session_id: str | None,
        start_time: float,
        reasoning_time: float,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Filter reasoning tags and build final response."""
        if isinstance(response, StreamingResponseEnvelope):
            # Filter stream
            response = await self.response_filter.filter_stream(response)
            # Prepend reasoning chunk
            response = self.response_builder.prepend_reasoning_to_stream(
                response,
                reasoning_output,
                reasoning_backend,
                reasoning_model,
            )
        else:
            # Type signature guarantees response is ResponseEnvelope | StreamingResponseEnvelope
            # If not StreamingResponseEnvelope, it must be ResponseEnvelope
            # Filter content
            filtered_content = self.response_filter.filter_content(response.content)
            # Add reasoning to message content (for backward compatibility with tests)
            # Check if connector has the wrapper method
            if (
                self._connector
                and hasattr(
                    self._connector, "_prepend_reasoning_to_non_streaming_content"
                )
                and callable(
                    self._connector._prepend_reasoning_to_non_streaming_content
                )
            ):
                # Use wrapper method which handles message content correctly
                # Pass None for formatted_reasoning so wrapper normalizes reasoning_output
                # to get the tagged version (with <think> tags)
                filtered_content = self._connector._prepend_reasoning_to_non_streaming_content(
                    content=filtered_content,
                    reasoning_output=reasoning_output,
                    reasoning_backend=reasoning_backend,
                    reasoning_model=reasoning_model,
                    formatted_reasoning=None,  # Let wrapper normalize to get tagged version
                )
            elif client_reasoning:
                # Fallback: add to metadata if wrapper not available
                if response.metadata is None:
                    response.metadata = {}
                response.metadata.setdefault("reasoning", client_reasoning)
                response.metadata.setdefault("reasoning_format", "hybrid_injected")
                response.metadata.setdefault("reasoning_backend", reasoning_backend)
                response.metadata.setdefault("reasoning_model", reasoning_model)
            # Convert filtered_content to proper type for ResponseEnvelope.content
            if (
                isinstance(filtered_content, dict | str | bytes)
                or filtered_content is None
            ):
                response.content = filtered_content
            elif hasattr(filtered_content, "model_dump"):
                response.content = filtered_content.model_dump()  # type: ignore[attr-defined]
            else:
                response.content = str(filtered_content)

        total_time = time.time() - start_time
        execution_time = total_time - reasoning_time

        logger.info(
            f"Hybrid request completed: total={total_time:.2f}s "
            f"(reasoning={reasoning_time:.2f}s, execution={execution_time:.2f}s)",
            extra={
                "session_id": session_id,
                "reasoning_backend": reasoning_backend,
                "reasoning_model": reasoning_model,
                "total_duration_seconds": total_time,
                "reasoning_duration_seconds": reasoning_time,
                "execution_duration_seconds": execution_time,
                "reasoning_output_length": len(reasoning_output),
            },
        )

        return response
