"""
Hybrid backend connector - orchestrates two-phase LLM interactions.

This connector implements a hybrid approach where:
1. A reasoning model generates chain-of-thought reasoning
2. The reasoning is captured and injected into the execution model's context
3. The execution model generates the final response with enhanced context
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from src.connectors.base import LLMBackend
from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
)
from src.connectors.hybrid_backend.compatibility import (
    HybridConnectorCompatibilityMixin,
)
from src.connectors.hybrid_backend.infrastructure import IdentityResolver, PhaseExecutor
from src.connectors.hybrid_backend.models import (
    HybridModelSpec,
    ReasoningPhaseResult,
)
from src.connectors.hybrid_backend.orchestration import (
    HybridOrchestrator,
    InjectionPolicy,
)
from src.connectors.hybrid_backend.services import (
    MessageAugmentor,
    ModelSpecParser,
    ParameterApplicator,
    ReasoningMarkupProcessor,
    ResponseBuilder,
    ResponseFilter,
)
from src.core.common.exceptions import InvalidRequestError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.services.backend_registry import backend_registry

if TYPE_CHECKING:
    from src.core.services.backend_registry import BackendRegistry
    from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)

# Note: time module is imported above for backward compatibility with tests
# Tests patch src.connectors.hybrid.time.time, but this patch path is incorrect
# The correct patch path would be time.time or orchestrator.time.time
# However, importing time here allows the test's incorrect patch to work

# Backward-compatible re-export
__all__ = ["HybridConnector", "HybridModelSpec", "ReasoningPhaseResult"]


class HybridConnector(LLMBackend, HybridConnectorCompatibilityMixin):
    """LLMBackend implementation for hybrid two-phase reasoning approach.

    This class serves as a backward-compatible facade, delegating all
    work to the modular HybridOrchestrator.
    """

    backend_type: str = "hybrid"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
        backend_registry: BackendRegistry | None = None,
    ) -> None:
        """Initialize the hybrid connector.

        Args:
            client: HTTP client for API calls
            config: Application configuration
            translation_service: Service for translating between formats
            backend_registry: Registry to resolve backend connectors
        """
        super().__init__(config=config)
        self.client = client
        self.config = config
        self.translation_service = translation_service
        self._backend_registry = backend_registry
        self._orchestrator = self._build_orchestrator(
            client, config, backend_registry, translation_service
        )

    def _build_orchestrator(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        backend_registry: BackendRegistry | None,
        translation_service: TranslationService,
    ) -> HybridOrchestrator:
        """Construct the orchestrator with injected dependencies.

        Dependency wiring order (bottom-up to avoid circular dependencies):
        1. Stateless services (no dependencies)
        2. Services with service dependencies
        3. Infrastructure (external I/O)
        4. Orchestration (stateful policy)
        5. Main orchestrator
        """
        # Layer 1: Stateless services (no dependencies)
        model_spec_parser = ModelSpecParser()
        reasoning_markup_processor = ReasoningMarkupProcessor()
        response_filter = ResponseFilter()
        identity_resolver = IdentityResolver(config)

        # Layer 2: Services with service dependencies
        parameter_applicator = ParameterApplicator()
        message_augmentor = MessageAugmentor(
            markup_processor=reasoning_markup_processor,
            config=config,
        )
        response_builder = ResponseBuilder(
            markup_processor=reasoning_markup_processor,
        )

        # Layer 3: Infrastructure (external I/O)
        phase_executor = PhaseExecutor(
            client=client,
            config=config,
            backend_registry=backend_registry,
            parameter_applicator=parameter_applicator,
            identity_resolver=identity_resolver,
            translation_service=translation_service,
            connector_ref=self,  # Pass self for backward compatibility with tests
        )

        # Layer 4: Orchestration (stateful policy)
        injection_policy = InjectionPolicy(config=config)

        # Layer 5: Main orchestrator
        # Pass self as connector for backward-compatible test patching
        return HybridOrchestrator(
            model_spec_parser=model_spec_parser,
            parameter_applicator=parameter_applicator,
            injection_policy=injection_policy,
            phase_executor=phase_executor,
            message_augmentor=message_augmentor,
            response_filter=response_filter,
            response_builder=response_builder,
            config=config,
            reasoning_markup_processor=reasoning_markup_processor,
            connector=self,
        )

    @property
    def _reasoning_backoff_remaining(self) -> int:
        """Backward-compatibility property for reasoning backoff state."""
        policy = getattr(self._orchestrator, "injection_policy", None)
        if policy is not None and hasattr(policy, "_reasoning_backoff_remaining"):
            return int(policy._reasoning_backoff_remaining or 0)
        return 0

    @_reasoning_backoff_remaining.setter
    def _reasoning_backoff_remaining(self, value: int) -> None:
        """Backward-compatibility setter for reasoning backoff state."""
        policy = getattr(self._orchestrator, "injection_policy", None)
        if policy is not None and hasattr(policy, "_reasoning_backoff_remaining"):
            policy._reasoning_backoff_remaining = int(value)

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize the hybrid backend.

        Note:
            Reasoning and execution models are specified per-request in the model field,
            not during initialization. The orchestrator and services are stateless
            (except InjectionPolicy), so initialization just resolves the backend
            registry if not provided.

        Args:
            **kwargs: Additional configuration (unused for hybrid backend)

        Raises:
            ConfigurationError: If hybrid backend is disabled in configuration
        """
        # Import backend_registry if not provided in constructor
        if self._backend_registry is None:
            from src.core.services.backend_registry import backend_registry

            self._backend_registry = backend_registry

        if logger.isEnabledFor(logging.INFO):
            logger.info("Hybrid backend initialized successfully")

    def get_available_models(self) -> list[str]:
        """Return available models for the hybrid backend.

        The hybrid backend is a meta-connector that composes other backends.
        It doesn't have its own models - instead, you specify backend:model
        pairs in the request using the format:
        "hybrid:[reasoning-backend:model,execution-backend:model]"

        Returns:
            Empty list - models are specified per-request, not enumerated.
        """
        return []

    async def chat_completions(  # type: ignore[override]
        self,
        request: ConnectorChatCompletionsRequest | Any = None,
        *args: Any,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Canonical connector API implementation with backward compatibility.

        This method implements ICanonicalChatCompletionsBackend protocol.
        For backward compatibility, also accepts legacy signature:
        chat_completions(request_data, processed_messages, effective_model, ...)
        """
        # Handle legacy API called with keyword arguments only (request_data=...)
        if request is None and "request_data" in kwargs:
            request = kwargs.pop("request_data")

        # Check if this is a canonical request (ConnectorChatCompletionsRequest)
        if isinstance(request, ConnectorChatCompletionsRequest):
            return await self._chat_completions_canonical(request)

        # Legacy API: build ConnectorChatCompletionsRequest from legacy parameters
        # BOUNDARY HARDENING: Legacy coercion is centralized at ConnectorInvoker.
        # This connector should only receive canonical domain models (never dicts).
        request_data = request
        processed_messages = args[0] if args else kwargs.get("processed_messages", [])
        effective_model = (
            args[1] if len(args) > 1 else kwargs.get("effective_model", "")
        )
        identity = kwargs.get("identity")
        cancellation_token = kwargs.get("cancellation_token")
        cancellation_coordinator = kwargs.get("cancellation_coordinator")
        context = None  # Legacy API doesn't provide context
        options = {
            k: v
            for k, v in kwargs.items()
            if k
            not in [
                "identity",
                "cancellation_token",
                "cancellation_coordinator",
                "processed_messages",
                "effective_model",
                "request_data",
            ]
        }

        # BOUNDARY HARDENING: Reject dict input - coercion should be centralized at ConnectorInvoker
        if isinstance(request_data, dict):
            raise InvalidRequestError(
                message="Legacy connector API received dict input. "
                "Dict-to-domain coercion is centralized at ConnectorInvoker boundary. "
                "Expected CanonicalChatRequest or ChatRequest.",
                details={
                    "received_type": "dict",
                    "connector": "hybrid",
                },
            )

        # Ensure processed_messages is a Sequence[ChatMessage]
        if processed_messages:
            invalid_messages = [
                (i, type(msg).__name__)
                for i, msg in enumerate(processed_messages)
                if not isinstance(msg, ChatMessage)
            ]
            if invalid_messages:
                raise InvalidRequestError(
                    message="Legacy connector API received non-canonical processed_messages. "
                    "Expected Sequence[ChatMessage], but received mixed types.",
                    details={
                        "invalid_indices": [idx for idx, _ in invalid_messages],
                        "invalid_types": [typ for _, typ in invalid_messages],
                        "connector": "hybrid",
                    },
                )

        # Accept only canonical domain models
        if isinstance(request_data, ChatRequest):
            domain_request = CanonicalChatRequest.model_validate(
                request_data.model_dump()
            )
        elif isinstance(request_data, CanonicalChatRequest):
            domain_request = request_data
        else:
            raise InvalidRequestError(
                message=f"Legacy connector API received invalid input type: {type(request_data).__name__}. "
                "Expected CanonicalChatRequest or ChatRequest.",
                details={
                    "received_type": type(request_data).__name__,
                    "connector": "hybrid",
                },
            )

        canonical_request = ConnectorChatCompletionsRequest(
            request=domain_request,
            processed_messages=processed_messages,
            effective_model=effective_model,
            identity=identity,
            cancellation_token=cancellation_token,
            cancellation_coordinator=cancellation_coordinator,
            context=context,
            options=options,
        )

        return await self._chat_completions_canonical(canonical_request)

    async def _chat_completions_canonical(
        self,
        request: ConnectorChatCompletionsRequest,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Canonical connector API implementation.

        This method implements ICanonicalChatCompletionsBackend protocol.
        It delegates to the orchestrator with canonical request data.
        """
        # Structural enforcement: check cancellation immediately if coordinator and token provided
        if (
            request.cancellation_coordinator is not None
            and request.cancellation_token is not None
        ):
            request.cancellation_coordinator.ensure_not_cancelled(
                request.cancellation_token
            )

        # Extract options for orchestrator
        options = request.options or {}

        # Delegate to orchestrator with canonical request contract
        # The orchestrator's execute method accepts canonical contracts only (CanonicalChatRequest | ChatRequest)
        # Dict-to-contract coercion is centralized at adapter boundaries (this connector's chat_completions method)
        return await self._orchestrator.execute(
            request_data=request.request,  # Already a canonical contract (CanonicalChatRequest)
            processed_messages=list(request.processed_messages),
            effective_model=request.effective_model,
            identity=request.identity,
            **options,
        )


# Register the hybrid backend
backend_registry.register_backend("hybrid", HybridConnector)
