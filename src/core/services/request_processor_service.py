"""
Request processor implementation.

This module provides the implementation of the request processor interface.
Refactored to use decomposed services following SOLID principles.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_request_manager_interface import IBackendRequestManager
from src.core.interfaces.command_processor_interface import ICommandProcessor
from src.core.interfaces.model_replacement_service_interface import (
    IModelReplacementService,
)
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.request_processor_internal import (
    IBackendExecutor,
    IBackendPreparer,
    ICommandHandler,
    IRequestSideEffects,
    IRequestTransformPipeline,
    ISessionEnricher,
)
from src.core.interfaces.response_manager_interface import IResponseManager
from src.core.interfaces.session_manager_interface import ISessionManager

logger = logging.getLogger(__name__)


class RequestProcessor(IRequestProcessor):
    """Implementation of the request processor using decomposed services."""

    def __init__(
        self,
        command_processor: ICommandProcessor,
        session_manager: ISessionManager,
        backend_request_manager: IBackendRequestManager,
        response_manager: IResponseManager,
        session_enricher: ISessionEnricher,
        request_side_effects: IRequestSideEffects,
        command_handler: ICommandHandler,
        backend_preparer: IBackendPreparer,
        transform_pipeline: IRequestTransformPipeline,
        backend_executor: IBackendExecutor,
        app_state: IApplicationState | None = None,
        replacement_service: IModelReplacementService | None = None,
    ) -> None:
        """Initialize the request processor with decomposed services.

        Args:
            command_processor: Legacy command processor interface (required)
            session_manager: Session management service (required)
            backend_request_manager: Backend request management service (required)
            response_manager: Response processing service (required)
            session_enricher: Session enrichment component (required)
            request_side_effects: Side effects component (streaming registry, memory) (required)
            command_handler: Command processing and early-return handler (required)
            backend_preparer: Backend request preparation and validation (required)
            transform_pipeline: Request transformation pipeline (redaction, precision, filtering) (required)
            backend_executor: Backend execution and persistence side effects (required)
            app_state: Application state for configuration and service access (optional)
            replacement_service: Model replacement service for fallback models (optional)
        """
        self._command_processor = command_processor
        self._session_manager = session_manager
        self._backend_request_manager = backend_request_manager
        self._response_manager = response_manager
        self._session_enricher = session_enricher
        self._request_side_effects = request_side_effects
        self._command_handler = command_handler
        self._backend_preparer = backend_preparer
        self._transform_pipeline = transform_pipeline
        self._backend_executor = backend_executor
        self._app_state = app_state
        self._replacement_service = replacement_service

    async def process_request(
        self, context: RequestContext, request_data: Any
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Process an incoming chat completion request using decomposed services."""
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"RequestProcessor.process_request called with session_id: {getattr(context, 'session_id', 'unknown')}"
            )
        if not isinstance(request_data, ChatRequest):
            raise TypeError("request_data must be of type ChatRequest")

        # Enrich session and client context
        from typing import cast

        from src.core.domain.session import Session

        enriched_session, request_data = await self._session_enricher.enrich(
            context, request_data
        )
        session = cast(Session, enriched_session)
        session_id = await self._session_manager.resolve_session_id(context)

        # Apply request side effects (streaming registry, memory injection/capture)
        request_data = await self._request_side_effects.apply(
            context, session_id, request_data
        )

        # Process commands and handle command-only flows
        result = await self._command_handler.handle(
            context, session, session_id, request_data
        )
        # If CommandHandler returns a response envelope, it took the command-only path
        if isinstance(result, ResponseEnvelope | StreamingResponseEnvelope):
            return result
        # Otherwise, it's a ProcessedResult and we continue with backend flow
        command_result = result

        # Apply model replacement if enabled
        # Note: Model replacement logic remains in RequestProcessor orchestrator rather than
        # being extracted to a dedicated component. This is intentional per research.md:
        # "In staged initialization wiring, the replacement service is currently not injected
        # into RequestProcessor, so this code path is typically inactive." If this feature
        # becomes more active or complex, consider extracting to a ModelReplacementHandler component.
        original_backend = getattr(context, "backend", None)
        original_model = request_data.model

        if self._replacement_service is not None and original_backend is not None:
            # Check if replacement should be triggered
            should_replace = self._replacement_service.should_replace(
                session_id, context
            )

            if should_replace:
                # Activate replacement if not already active
                state = self._replacement_service.get_state(session_id)
                if not state.active:
                    await self._replacement_service.activate_replacement(
                        session_id, original_backend, original_model
                    )

                # Get effective backend:model
                effective_backend, effective_model = (
                    self._replacement_service.get_effective_backend_model(
                        session_id, original_backend, original_model
                    )
                )

                # Update backend and model
                original_backend = effective_backend
                request_data = request_data.model_copy(
                    update={"model": effective_model}
                )

        # Prepare and validate backend request
        backend_request = await self._backend_preparer.prepare(
            context, session_id, request_data, command_result
        )
        if backend_request is None:
            # Backend should be skipped; command result is already the final result
            return await self._response_manager.process_command_result(
                command_result, session
            )

        # Apply request transformations using pipeline
        # Note: transform() always returns ChatRequest (never None) per IRequestTransformPipeline contract
        backend_request = await self._transform_pipeline.transform(
            context, session, session_id, backend_request
        )

        # Execute backend and perform persistence side effects
        return await self._backend_executor.execute(
            context, session, session_id, backend_request, request_data
        )
