"""
Chat completion coordinator for Gemini connectors.

This module provides the GeminiChatCompletionCoordinator class that orchestrates
streaming and non-streaming chat completion flows.
"""

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.connectors.gemini_base.chat_request_preparer import ChatRequestPreparer
from src.connectors.gemini_base.connector_context import IThoughtSignatureService
from src.connectors.gemini_base.interfaces import (
    IChatCompletionCoordinator,
    ICodeAssistOrchestrator,
    IEndpointConfig,
    IErrorMapper,
    IVtcWrapperBuilder,
)
from src.connectors.gemini_base.streaming_executor import ITokenRefresher
from src.core.common.exceptions import BackendError, InvalidRequestError
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope

if TYPE_CHECKING:
    from src.core.domain.chat import CanonicalChatRequest, ChatMessage

logger = logging.getLogger(__name__)


class GeminiChatCompletionCoordinator(IChatCompletionCoordinator):
    """Orchestrates streaming and non-streaming chat completion flows.

    This coordinator delegates to request preparation, execution, and response
    accumulation services while preserving response envelopes and chunk ordering.
    """

    def __init__(
        self,
        *,
        request_preparer: ChatRequestPreparer,
        orchestrator: ICodeAssistOrchestrator,
        token_refresher: ITokenRefresher,
        endpoint_config: IEndpointConfig,
        api_base_url: str,
        backend_type: str = "gemini",
        vtc_wrapper_builder: IVtcWrapperBuilder | None = None,
        error_mapper: IErrorMapper | None = None,
        thought_signature_service: IThoughtSignatureService | None = None,
        key_name: str | None = None,
    ) -> None:
        """Initialize the chat completion coordinator.

        Args:
            request_preparer: Service for preparing chat requests.
            orchestrator: Service for executing streaming/non-streaming requests.
            token_refresher: Interface for token refresh operations.
            endpoint_config: Configuration for API endpoints.
            api_base_url: Base URL for the Gemini API.
            backend_type: Backend type identifier for error mapping and logging.
            vtc_wrapper_builder: Optional builder for VTC streaming wrappers.
            error_mapper: Optional mapper for error normalization.
            thought_signature_service: Optional service for thought signature management.
            key_name: Optional key name for logging.
        """
        self._request_preparer = request_preparer
        self._orchestrator = orchestrator
        self._token_refresher = token_refresher
        self._endpoint_config = endpoint_config
        self._api_base_url = api_base_url
        self._backend_type = backend_type
        self._vtc_wrapper_builder = vtc_wrapper_builder
        self._error_mapper = error_mapper
        self._thought_signature_service = thought_signature_service
        self._key_name = key_name

    async def execute(
        self,
        request_data: "CanonicalChatRequest",
        processed_messages: list["ChatMessage"],
        *,
        effective_model: str,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Return a streaming or non-streaming response envelope.

        Args:
            request_data: The canonical chat request.
            processed_messages: Pre-processed chat messages (currently unused, preserved for interface compatibility).
            effective_model: The model name to use.

        Returns:
            ResponseEnvelope for non-streaming, StreamingResponseEnvelope for streaming.

        Raises:
            BackendError: If execution fails.
            InvalidRequestError: If request is invalid.
        """
        # Determine if this is a streaming request
        is_streaming = getattr(request_data, "stream", False) or False

        try:
            # Prepare the request
            prepared_start = time.monotonic()
            prepared = await self._request_preparer.prepare(
                request_data=request_data,
                effective_model=effective_model,
                is_streaming=is_streaming,
            )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Prepared %s request in %.3fs (model=%s, session=%s)",
                    "streaming" if is_streaming else "non-streaming",
                    time.monotonic() - prepared_start,
                    effective_model,
                    getattr(request_data, "session_id", None),
                )

            # Build the API URL
            url = f"{self._api_base_url}/v1internal:streamGenerateContent"
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Making %s Code Assist API call to: %s",
                    "streaming" if is_streaming else "non-streaming",
                    url,
                )

            # Build VTC wrapper if enabled and builder is available

            stream_wrapper = None
            if is_streaming and self._vtc_wrapper_builder is not None:
                stream_wrapper = self._vtc_wrapper_builder.build(
                    request_data=request_data,
                    effective_model=effective_model,
                )

            # Build thought signature callback if service is available
            thought_signature_callback: (
                Callable[[list[dict[str, Any]], str | None], None] | None
            ) = None
            thought_signature_service = self._thought_signature_service
            if thought_signature_service is not None:

                def callback(
                    tool_calls: list[dict[str, Any]], session_id: str | None
                ) -> None:
                    thought_signature_service.store_signatures_from_tool_calls(
                        tool_calls,
                        session_id,
                    )

                thought_signature_callback = callback

            # Execute via orchestrator
            response: ResponseEnvelope | StreamingResponseEnvelope
            if is_streaming:
                response = await self._orchestrator.run_streaming(
                    prepared=prepared,
                    url=url,
                    token_refresher=self._token_refresher,
                    thought_signature_callback=thought_signature_callback,
                    key_name=self._key_name,
                    stream_wrapper=stream_wrapper,
                )
            else:
                response = await self._orchestrator.run_non_streaming(
                    prepared=prepared,
                    url=url,
                    token_refresher=self._token_refresher,
                    thought_signature_callback=thought_signature_callback,
                    key_name=self._key_name,
                )

            # Note: Response envelope may contain error chunks (504, 429, etc.)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Received response envelope from Code Assist API")

            return response

        except InvalidRequestError:
            # Let invalid request errors bubble up unchanged
            raise
        except Exception as e:
            # Normalize other exceptions if error mapper is available
            if self._error_mapper is not None:
                try:
                    mapped_error = self._error_mapper.map_exception(
                        e, backend_name=self._backend_type
                    )
                    # map_exception returns LLMProxyError (or raises HTTPException)
                    raise mapped_error from e
                except Exception as mapped_exc:
                    # If map_exception raised HTTPException, re-raise it
                    # (HTTPException must be raised, not returned, for FastAPI)
                    raise mapped_exc from e

            # If no error mapper, wrap in BackendError
            logger.error(
                f"Unexpected error during {'streaming' if is_streaming else 'non-streaming'} API call: {e}",
                exc_info=True,
            )
            raise BackendError(
                message=f"{self._backend_type} chat completion failed: {e!s}",
                backend_name=self._backend_type,
            ) from e


__all__ = ["GeminiChatCompletionCoordinator"]
