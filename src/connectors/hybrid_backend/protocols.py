"""Protocols for hybrid backend services.

This module defines the contracts for all services in the hybrid_backend package.
Following the Interface Segregation Principle, each protocol is focused and minimal.

Requirements satisfied:
- 3: Protocol-first design for all services
- 4: Dependency Inversion via Protocol interfaces
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.connectors.hybrid_backend.models.injection_decision import (
        InjectionDecision,
    )
    from src.connectors.hybrid_backend.models.model_spec import HybridModelSpec
    from src.connectors.hybrid_backend.models.phase_result import ReasoningPhaseResult
    from src.connectors.hybrid_backend.models.reasoning_text import ReasoningText
    from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
    from src.core.interfaces.configuration_interface import IAppIdentityConfig
    from src.core.interfaces.model_bases import DomainModel, InternalDTO


@runtime_checkable
class IModelSpecParser(Protocol):
    """Protocol for parsing hybrid model specification strings.

    Requirements satisfied:
    - Req 2.1: ModelSpecParser extraction
    - Req 3: Protocol-first design for all services
    """

    def parse(self, model_spec: str) -> HybridModelSpec:
        """Parse hybrid model specification.

        Args:
            model_spec: Format "hybrid:[backend:model?params,backend:model?params]"

        Returns:
            Parsed HybridModelSpec

        Raises:
            ValueError: If format is invalid
        """
        ...


@runtime_checkable
class IParameterApplicator(Protocol):
    """Protocol for applying phase-specific parameters to requests.

    Requirements satisfied:
    - Req 2.2: ParameterApplicator extraction
    - Req 3: Protocol-first design for all services
    """

    def apply_reasoning_params(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        backend: str,
        params: dict[str, Any] | None = None,
    ) -> DomainModel | InternalDTO | dict[str, Any]:
        """Apply reasoning-phase parameters to request data.

        Args:
            request_data: Request data in various formats (Pydantic model, dict, etc.)
            backend: Backend name for parameter lookup
            params: Optional parameter overrides

        Returns:
            Modified request data with reasoning parameters applied
        """
        ...

    def apply_execution_params(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        backend: str,
        params: dict[str, Any] | None = None,
    ) -> DomainModel | InternalDTO | dict[str, Any]:
        """Apply execution-phase parameters to request data.

        Args:
            request_data: Request data in various formats (Pydantic model, dict, etc.)
            backend: Backend name for parameter lookup
            params: Optional parameter overrides

        Returns:
            Modified request data with execution parameters applied
        """
        ...


@runtime_checkable
class IReasoningMarkupProcessor(Protocol):
    """Protocol for reasoning markup tag processing.

    Requirements satisfied:
    - Req 2.4: ReasoningMarkupProcessor extraction
    - Req 3: Protocol-first design for all services
    """

    def normalize(self, reasoning_output: str, backend: str) -> ReasoningText:
        """Normalize reasoning markup to canonical format.

        Args:
            reasoning_output: Raw reasoning text with potentially malformed tags
            backend: Backend name for tag format selection

        Returns:
            ReasoningText containing tagged and plain text representations
        """
        ...

    def format_for_model(self, reasoning_output: str, backend: str) -> str:
        """Format reasoning with backend-specific tags.

        Args:
            reasoning_output: Raw reasoning text
            backend: Backend name for format selection

        Returns:
            Formatted reasoning with appropriate tags
        """
        ...

    def extract_plain_text(self, reasoning_output: str) -> str:
        """Strip all tags and return plain text.

        Args:
            reasoning_output: Tagged reasoning text

        Returns:
            Plain text with all tags removed
        """
        ...


@runtime_checkable
class IMessageAugmentor(Protocol):
    """Protocol for injecting reasoning into message lists.

    Requirements satisfied:
    - Req 2.3: MessageAugmentor extraction
    - Req 3: Protocol-first design for all services
    """

    def augment(
        self,
        messages: list[Any],
        reasoning_output: str,
        execution_backend: str,
    ) -> list[Any]:
        """Inject reasoning into messages using appropriate strategy.

        Args:
            messages: Original message list
            reasoning_output: Captured reasoning text
            execution_backend: Backend name to determine injection strategy

        Returns:
            New message list with reasoning injected appropriately.
            Strategy depends on backend capabilities:
            - System message injection if backend supports system role
            - User message prepending otherwise
        """
        ...


@runtime_checkable
class IResponseFilter(Protocol):
    """Protocol for filtering reasoning tags from responses.

    Requirements satisfied:
    - Req 2.5: ResponseFilter extraction
    - Req 3: Protocol-first design for all services
    """

    def filter_content(self, content: Any) -> Any:
        """Filter reasoning tags from response content.

        Args:
            content: Response content (can be string, dict, bytes, or list)

        Returns:
            Filtered content with reasoning tags removed
        """
        ...

    async def filter_stream(
        self, response: StreamingResponseEnvelope
    ) -> StreamingResponseEnvelope:
        """Filter reasoning tags from streaming response.

        Args:
            response: Original streaming response from execution model

        Returns:
            Filtered streaming response with reasoning tags removed
        """
        ...


@runtime_checkable
class IResponseBuilder(Protocol):
    """Protocol for constructing response envelopes.

    Requirements satisfied:
    - Req 2.6: ResponseBuilder extraction
    - Req 3: Protocol-first design for all services
    """

    def build_reasoning_chunk(
        self,
        reasoning_output: str,
        reasoning_backend: str,
        reasoning_model: str,
    ) -> Any:
        """Build a streaming chunk containing reasoning preview.

        Args:
            reasoning_output: Captured reasoning text
            reasoning_backend: Backend name for metadata
            reasoning_model: Model name for metadata

        Returns:
            ProcessedResponse chunk or None if no reasoning content
        """
        ...

    def build_tool_call_response(
        self,
        tool_calls: list[dict[str, Any]],
        request_dict: dict[str, Any],
        backend: str,
        model: str,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Build response for tool-call-only scenarios.

        Args:
            tool_calls: Tool calls from reasoning phase
            request_dict: Original request dictionary
            backend: Backend name for response metadata
            model: Model name for response metadata

        Returns:
            Response envelope (streaming or non-streaming) containing tool calls
        """
        ...

    def prepend_reasoning_to_stream(
        self,
        response: StreamingResponseEnvelope,
        reasoning_output: str,
        reasoning_backend: str,
        reasoning_model: str,
    ) -> StreamingResponseEnvelope:
        """Prepend reasoning chunk to streaming response.

        Args:
            response: Original streaming response
            reasoning_output: Captured reasoning text
            reasoning_backend: Backend name for metadata
            reasoning_model: Model name for metadata

        Returns:
            New streaming response with reasoning chunk prepended.
            Must preserve cancel_callback from original response.
        """
        ...


@runtime_checkable
class IInjectionPolicy(Protocol):
    """Protocol for reasoning injection decisions.

    This protocol defines a stateful policy engine that maintains adaptive
    backoff state across requests. Implementations should maintain per-instance
    state for backoff tracking.

    Requirements satisfied:
    - Req 8: Injection Policy Extraction
    - Req 3: Protocol-first design for all services
    """

    def should_inject(
        self,
        processed_messages: list[Any] | None,
        request_messages: list[Any] | None,
        probability_override: float | None = None,
        identity: IAppIdentityConfig | None = None,
    ) -> InjectionDecision:
        """Determine whether reasoning should be injected.

        Args:
            processed_messages: Messages after command processing
            request_messages: Original request messages
            probability_override: Optional probability override for this request
            identity: Optional identity configuration (for turn count)

        Returns:
            InjectionDecision containing decision, reason, and metadata
        """
        ...

    def update_backoff(self, success: bool) -> None:
        """Update adaptive backoff state based on phase outcome.

        Args:
            success: Whether the reasoning phase completed successfully
        """
        ...


@runtime_checkable
class IPhaseExecutor(Protocol):
    """Protocol for executing reasoning and execution phases.

    Requirements satisfied:
    - Req 9: Phase Executor Extraction
    - Req 3: Protocol-first design for all services
    """

    async def execute_reasoning_phase(
        self,
        messages: list[Any],
        reasoning_backend: str,
        reasoning_model: str,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        identity: IAppIdentityConfig | None,
        uri_params: dict[str, Any] | None = None,
    ) -> ReasoningPhaseResult:
        """Execute reasoning phase and return captured output.

        Args:
            messages: Original message history
            reasoning_backend: Backend name for reasoning model
            reasoning_model: Model name for reasoning
            request_data: Original request data
            identity: Optional identity configuration
            uri_params: Optional URI parameter overrides

        Returns:
            Structured result containing reasoning text, tool calls, and stream metadata

        Raises:
            BackendError: If reasoning model call fails (HTTP 502)
            TimeoutError: If reasoning phase times out (HTTP 504)
        """
        ...

    async def execute_execution_phase(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        augmented_messages: list[Any],
        execution_backend: str,
        execution_model: str,
        identity: IAppIdentityConfig | None,
        uri_params: dict[str, Any] | None = None,
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
            **kwargs: Additional arguments

        Returns:
            Response from execution model

        Raises:
            BackendError: If execution model call fails (HTTP 502)
        """
        ...


@runtime_checkable
class IHybridOrchestrator(Protocol):
    """Protocol for the main hybrid orchestration flow.

    Requirements satisfied:
    - Req 7: Orchestrator Extraction
    - Req 3: Protocol-first design for all services
    """

    async def execute(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        processed_messages: list[Any],
        effective_model: str,
        identity: IAppIdentityConfig | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute the complete two-phase hybrid completion.

        Args:
            request_data: Original request
            processed_messages: Messages after command processing
            effective_model: Format "hybrid:[backend:model,backend:model]"
            identity: Optional identity configuration
            **kwargs: Additional arguments

        Returns:
            Response envelope (streaming or non-streaming) with execution model's response

        Raises:
            ValueError: If model specification is invalid
            BackendError: If either phase fails (HTTP 502)
        """
        ...
