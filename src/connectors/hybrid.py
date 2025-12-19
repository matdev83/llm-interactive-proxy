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
from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.model_bases import DomainModel, InternalDTO
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
        # Cast to concrete type to access private attribute
        from src.connectors.hybrid_backend.orchestration.injection_policy import (
            InjectionPolicy,
        )

        if isinstance(self._orchestrator.injection_policy, InjectionPolicy):
            return self._orchestrator.injection_policy._reasoning_backoff_remaining
        return 0

    @_reasoning_backoff_remaining.setter
    def _reasoning_backoff_remaining(self, value: int) -> None:
        """Backward-compatibility setter for reasoning backoff state."""
        # Cast to concrete type to access private attribute
        from src.connectors.hybrid_backend.orchestration.injection_policy import (
            InjectionPolicy,
        )

        if isinstance(self._orchestrator.injection_policy, InjectionPolicy):
            self._orchestrator.injection_policy._reasoning_backoff_remaining = value

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

    async def chat_completions(
        self,
        request_data: DomainModel | InternalDTO | dict[str, Any],
        processed_messages: list,
        effective_model: str,
        identity: IAppIdentityConfig | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Execute the two-phase hybrid completion.

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
            ConfigurationError: If hybrid backend is disabled
            BackendError: If either phase fails (HTTP 502)
        """
        return await self._orchestrator.execute(
            request_data=request_data,
            processed_messages=processed_messages,
            effective_model=effective_model,
            identity=identity,
            **kwargs,
        )


# Register the hybrid backend
backend_registry.register_backend("hybrid", HybridConnector)
