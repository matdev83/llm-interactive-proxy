"""
Backend request manager implementation.

This module provides the implementation of the backend request manager interface.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.common.exceptions import BackendError, DuplicateRequestError
from src.core.domain.backend_request_manager.context_models import (
    ResponseProcessingContext,
    StructuredOutputContext,
)
from src.core.domain.chat import ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.angel_service_interface import IAngelServiceFactory
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.backend_request_manager_components import (
    IBackendRequestPreparation,
    INonStreamingBackendResponseHandler,
    IStreamingBackendResponseHandler,
)
from src.core.interfaces.backend_request_manager_interface import IBackendRequestManager
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.request_deduplication_interface import (
    IRequestDeduplicationService,
)
from src.core.interfaces.response_processor_interface import (
    IResponseProcessor,
)
from src.core.services.history_compaction_service import HistoryCompactionService

logger = logging.getLogger(__name__)


class BackendRequestManager(IBackendRequestManager):
    """Implementation of the backend request manager."""

    def __init__(
        self,
        backend_processor: IBackendProcessor,
        response_processor: IResponseProcessor,
        angel_service_factory: IAngelServiceFactory,
        request_preparation: IBackendRequestPreparation,
        non_streaming_handler: INonStreamingBackendResponseHandler,
        streaming_handler: IStreamingBackendResponseHandler,
        wire_capture: Any | None = None,
        history_compaction_service: HistoryCompactionService | None = None,
        config: IConfig | None = None,
        dedup_service: IRequestDeduplicationService | None = None,
    ) -> None:
        """Initialize the backend request manager.

        Args:
            backend_processor: The backend processor
            response_processor: The response processor
            angel_service_factory: Factory for modifying schemas
            request_preparation: Service for preparing backend requests
            non_streaming_handler: Handler for non-streaming responses
            streaming_handler: Handler for streaming responses
            wire_capture: Optional wire capture service
            history_compaction_service: Optional service for compacting history (kept for backward compatibility)
            config: Optional application configuration (kept for backward compatibility)
            dedup_service: Optional request deduplication service
        """
        self._backend_processor = backend_processor
        if angel_service_factory is None:
            raise ValueError("angel_service_factory is required")
        self._response_processor = response_processor
        self._angel_service_factory = angel_service_factory
        self._request_preparation = request_preparation
        self._non_streaming_handler = non_streaming_handler
        self._streaming_handler = streaming_handler
        self._history_compaction_service = history_compaction_service
        self._config = config
        self._dedup_service = dedup_service
        # wire_capture is currently applied at BackendService level to avoid
        # duplicating backend resolution logic; accepted here for future use.

    def _build_processing_context(
        self,
        request: ChatRequest,
        session_id: str,
        context: RequestContext,
    ) -> ResponseProcessingContext:
        """Build ResponseProcessingContext from request and context.

        Args:
            request: The backend request
            session_id: Session identifier
            context: Request context with processing_context

        Returns:
            Typed processing context with all required fields
        """
        # Extract backend_name from extra_body or model
        backend_name: str | None = None
        extra_body = getattr(request, "extra_body", None)
        if isinstance(extra_body, dict):
            backend_name = extra_body.get("backend_type")
        if backend_name is None:
            backend_name = getattr(request, "model", None)

        # Extract model_name from request
        model_name = getattr(request, "model", None)

        # Extract client_os from processing_context if available
        client_os: str | None = None
        if context.processing_context is not None:
            processing_values = context.processing_context.values
            if isinstance(processing_values, dict):
                client_os = processing_values.get("client_os")

        # Build structured output context if schema is present
        structured_output: StructuredOutputContext | None = None
        if context.processing_context is not None:
            processing_values = context.processing_context.values
            if isinstance(processing_values, dict):
                response_schema = processing_values.get("response_schema")
                if response_schema is not None:
                    schema_name = processing_values.get("schema_name", "unnamed")
                    request_id = processing_values.get("request_id", session_id)
                    structured_output = StructuredOutputContext(
                        schema=response_schema,
                        schema_name=str(schema_name),
                        request_id=str(request_id),
                    )

        return ResponseProcessingContext(
            session_id=session_id,
            backend_name=backend_name,
            model_name=model_name,
            client_os=client_os,
            original_request=request,
            structured_output=structured_output,
        )

    async def prepare_backend_request(
        self, request_data: ChatRequest, command_result: ProcessedResult
    ) -> ChatRequest | None:
        """Prepare backend request based on command processing results."""
        return await self._request_preparation.prepare(request_data, command_result)

    async def process_backend_request(
        self,
        backend_request: ChatRequest,
        session_id: str,
        context: RequestContext,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Process backend request with retry handling."""
        content_hash: str | None = None
        # Deduplication check FIRST (before any processing)
        if self._dedup_service:
            is_duplicate, content_hash = await self._dedup_service.check_and_register(
                backend_request, session_id
            )
            if is_duplicate:
                # Use debug level to avoid log spam during tight retry loops
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Duplicate request swallowed: hash=%s session=%s model=%s",
                        content_hash[:8],
                        session_id,
                        backend_request.model,
                    )
                raise DuplicateRequestError(content_hash, session_id)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Submitting backend request: hash=%s session=%s model=%s stream=%s",
                content_hash[:8] if content_hash else "n/a",
                session_id,
                backend_request.model,
                getattr(backend_request, "stream", False),
            )

        # Build processing context once per request
        processing_context = self._build_processing_context(
            backend_request, session_id, context
        )

        # Execute backend request
        backend_response = await self._backend_processor.process_backend_request(
            request=backend_request, session_id=session_id, context=context
        )

        # Route to appropriate handler based on stream flag
        if backend_request.stream:
            if isinstance(backend_response, StreamingResponseEnvelope):
                try:
                    return await self._streaming_handler.handle(
                        stream=backend_response,
                        request=backend_request,
                        context=context,
                        processing_context=processing_context,
                    )
                except BackendError as e:
                    # Re-raise BackendError from streaming handler to preserve error details
                    # (Req 1.4, Task 6.2: empty-stream retry exhaustion raises BackendError with reason and session_id)
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "BackendError from streaming handler: %s (session_id=%s)",
                            e.message,
                            processing_context.session_id,
                        )
                    raise
            else:
                # This case should ideally not be reached if the logic is correct
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Expected a StreamingResponseEnvelope but got a ResponseEnvelope for a streaming request."
                    )
                return backend_response
        else:
            if isinstance(backend_response, ResponseEnvelope):
                try:
                    return await self._non_streaming_handler.handle(
                        response=backend_response,
                        request=backend_request,
                        context=context,
                        processing_context=processing_context,
                    )
                except BackendError as e:
                    # Re-raise BackendError from non-streaming handler to preserve error details
                    # (Req 1.4: empty-response retry exhaustion raises BackendError with reason and session_id)
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "BackendError from non-streaming handler: %s (session_id=%s)",
                            e.message,
                            processing_context.session_id,
                        )
                    raise
            else:
                # This case should ideally not be reached if the logic is correct
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Expected a ResponseEnvelope but got a StreamingResponseEnvelope for a non-streaming request."
                    )
                return backend_response
