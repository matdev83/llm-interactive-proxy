"""
Angel stream verifier service.

This service buffers and verifies streaming output when Angel verification is enabled,
returning corrected output when steering decisions occur.

Requirements: 4.5, 5.5
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any, cast

from src.core.domain.backend_request_manager.context_models import StreamingContext
from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.interfaces.backend_request_manager_components import (
    IAngelStreamVerifier,
)
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.session_cancellation_coordinator_interface import (
    ISessionCancellationCoordinator,
)
from src.core.services.angel_service import AngelService
from src.core.transport.session_key_resolver import (
    resolve_session_key_from_request_context,
)

logger = logging.getLogger(__name__)


class AngelStreamVerifier(IAngelStreamVerifier):
    """Service for buffering and verifying streaming output when Angel is enabled."""

    def __init__(
        self,
        angel_service_factory: Any,  # IAngelServiceFactory
        provider: IServiceProvider,
        cancellation_coordinator: ISessionCancellationCoordinator | None = None,
    ) -> None:
        """Initialize the Angel stream verifier.

        Args:
            angel_service_factory: Factory for creating AngelService instances
            provider: Service provider for resolving IBackendService
            cancellation_coordinator: Coordinator for session cancellation checks
        """
        self._angel_service_factory = angel_service_factory
        self._provider = provider
        self._cancellation_coordinator = cancellation_coordinator

    def _extract_text_from_chunk(self, chunk: ProcessedResponse) -> str:
        """Extract textual content from a streaming chunk."""
        content = chunk.content
        if isinstance(content, str):
            return content
        if isinstance(content, bytes):
            try:
                return content.decode("utf-8")
            except Exception:
                return content.decode("utf-8", errors="ignore")
        return str(content) if content is not None else ""

    def _extract_text_from_response(self, payload: Any) -> str:
        """Extract text from backend response payload."""
        if payload is None:
            return ""
        value = getattr(payload, "content", payload)
        if isinstance(value, str):
            return value
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8")
            except Exception:
                return value.decode("utf-8", errors="ignore")
        return str(value)

    async def verify_or_passthrough(  # type: ignore[override, misc]
        self,
        request: ChatRequest,
        stream: AsyncIterator[ProcessedResponse],
        context: StreamingContext,
        request_context: RequestContext | None = None,
    ) -> AsyncIterator[ProcessedResponse]:
        """Return verified stream or original stream when no steering is needed.

        Args:
            request: The original backend request
            stream: The streaming response chunks
            context: Streaming context with session_id, stream_id, angel_model_spec, angel_frequency, etc.

        Yields:
            ProcessedResponse chunks (verified or original)
        """
        # Check if Angel verification should run
        angel_model_spec: str | None = context.get("angel_model_spec")
        angel_frequency: int = context.get("angel_frequency", 1)

        should_buffer = False
        angel_service_instance: AngelService | None = None

        if (
            angel_model_spec
            and isinstance(request, ChatRequest)
            and AngelService.should_run_for_request(request, angel_frequency)
        ):
            try:
                angel_service_instance = self._angel_service_factory.create(
                    angel_model_spec
                )
                if (
                    angel_service_instance is not None
                    and angel_service_instance.is_enabled()
                ):
                    should_buffer = True
            except Exception:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to initialize Angel service for verification",
                        exc_info=True,
                    )

        # If Angel verification is not enabled, pass through original stream
        if not should_buffer:
            async for chunk in stream:
                yield chunk
            return

        # Buffer chunks for verification
        buffered_chunks: list[ProcessedResponse] = []
        text_fragments: list[str] = []

        async for chunk in stream:
            buffered_chunks.append(chunk)
            text_piece = self._extract_text_from_chunk(chunk)
            if text_piece:
                text_fragments.append(text_piece)

        if not buffered_chunks:
            return

        combined_text = "".join(text_fragments)
        if not combined_text.strip():
            # Empty text, just yield buffered chunks
            for buffered in buffered_chunks:
                yield buffered
            return

        # Perform verification
        try:
            backend_service: IBackendService = self._provider.get_required_service(
                cast(type, IBackendService)
            )

            if not angel_service_instance:
                # Should not happen given the check above, but safe fallback
                created_instance = self._angel_service_factory.create(
                    angel_model_spec or ""
                )
                if created_instance is None:
                    # Fail-open: return original chunks if service creation fails
                    for buffered in buffered_chunks:
                        yield buffered
                    return
                angel_service_instance = created_instance

            # Type guard: ensure angel_service_instance is not None
            if angel_service_instance is None:
                for buffered in buffered_chunks:
                    yield buffered
                return

            verification_request = angel_service_instance.build_verification_request(
                request, combined_text
            )

            # Cancellation gate: ensure session is not cancelled before Angel verification backend call
            if self._cancellation_coordinator and request_context:
                session_key = resolve_session_key_from_request_context(request_context)
                if session_key:
                    self._cancellation_coordinator.ensure_not_cancelled(session_key)

            angel_response = await backend_service.chat_completions(
                verification_request,
                stream=False,
                allow_failover=True,
                context=request_context,
            )
            angel_text = self._extract_text_from_response(angel_response)

            decision = angel_service_instance.parse_angel_output(angel_text)
            steering_msg = (decision.steering_message or "").strip()

            # If no steering needed, pass through original chunks
            if decision.decision != "steer" or not steering_msg:
                for buffered in buffered_chunks:
                    yield buffered
                return

            # Build correction request and get corrected response
            correction_request = angel_service_instance.build_correction_request(
                request, combined_text, steering_msg
            )

            # Cancellation gate: ensure session is not cancelled before Angel correction backend call
            if self._cancellation_coordinator and request_context:
                session_key = resolve_session_key_from_request_context(request_context)
                if session_key:
                    self._cancellation_coordinator.ensure_not_cancelled(session_key)

            corrected_response = await backend_service.chat_completions(
                correction_request,
                stream=False,
                allow_failover=True,
                context=request_context,
            )
            corrected_text = self._extract_text_from_response(corrected_response)

            # Check for override marker
            if angel_service_instance.has_override_marker(corrected_text):
                for buffered in buffered_chunks:
                    yield buffered
                return

            # Yield corrected output with steering replacement marker
            cleaned = angel_service_instance.strip_override_marker(corrected_text)
            yield ProcessedResponse(
                content=cleaned,
                metadata={
                    "corrected_by_angel": True,
                    "is_done": True,
                    "angel_decision": "steer",
                    "_steering_replacement": True,
                },
            )

        except Exception:
            # Fail-open: log error and return original chunks
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Angel streaming verification failed; forwarding original chunks",
                    exc_info=True,
                )
            for buffered in buffered_chunks:
                yield buffered
