"""
Backend executor implementation.

This module provides the BackendExecutor service that handles backend
invocation and required persistence side effects (session history updates,
fingerprint updates, turn completion).
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_request_manager_interface import (
    IBackendRequestManager,
)
from src.core.interfaces.model_replacement_service_interface import (
    IModelReplacementService,
)
from src.core.interfaces.request_processor_internal import IBackendExecutor
from src.core.interfaces.session_manager_interface import ISessionManager

logger = logging.getLogger(__name__)


class BackendExecutor(IBackendExecutor):
    """
    Handles backend execution and persistence side effects.

    Responsibilities:
    - Inject session ID into request metadata
    - Invoke backend via BackendRequestManager
    - Update session history after successful execution
    - Best-effort fingerprint updates
    - Ensure turn completion runs in finally block (when replacement service exists)
    """

    def __init__(
        self,
        backend_request_manager: IBackendRequestManager,
        session_manager: ISessionManager,
        replacement_service: IModelReplacementService | None = None,
    ) -> None:
        """
        Initialize the backend executor.

        Args:
            backend_request_manager: Manages backend request processing
            session_manager: Manages session state and history
            replacement_service: Optional service for model replacement turn completion
        """
        self._backend_request_manager = backend_request_manager
        self._session_manager = session_manager
        self._replacement_service = replacement_service

    async def execute(
        self,
        context: RequestContext,
        session: object,
        session_id: str,
        request: ChatRequest,
        original_request: ChatRequest,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """
        Execute backend call and perform required side effects.

        Args:
            context: Request context containing headers, cookies, etc.
            session: Session object (not directly used but passed for consistency)
            session_id: Session identifier
            request: Transformed backend request ready for execution
            original_request: Original user request before transformations (for history)

        Returns:
            Backend response envelope (unmodified)

        Raises:
            Backend errors propagate unchanged

        Requirements:
            - 1.4: Return backend response without transformation
            - 1.5: Update session history with same inputs as current implementation
            - 1.6: Best-effort fingerprint updates (fail-open)
            - 1.7: Turn completion in finally block when replacement state exists
            - 10.1: Inject session_id into extra_body prior to execution
            - 10.2: Backend invocation with current session ID and context
            - 10.3: Session history updated after backend execution completes
            - 10.4: Backend errors propagate unchanged
        """
        # Inject session_id into extra_body and session_id field (Req 10.1)
        final_extra_body_attr = getattr(request, "extra_body", None)
        final_extra_body: dict[str, Any] = (
            final_extra_body_attr.copy() if final_extra_body_attr else {}
        )
        if "session_id" not in final_extra_body:
            final_extra_body["session_id"] = session_id
        request = request.model_copy(
            update={"extra_body": final_extra_body, "session_id": session_id}
        )

        # Log backend invocation
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                f"Calling backend for session {session_id} with model: {getattr(request, 'model', 'unknown')}"
            )

        try:
            # Call backend (Req 10.2, 10.4)
            backend_response = (
                await self._backend_request_manager.process_backend_request(
                    request, session_id, context
                )
            )
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    f"Backend response for session {session_id}: {type(backend_response).__name__}"
                )

            # Update session history (Req 10.3, 1.5)
            await self._session_manager.update_session_history(
                original_request, request, backend_response, session_id
            )

            # Best-effort fingerprint update (Req 1.6)
            if hasattr(self._session_manager, "update_session_fingerprint"):
                try:
                    await self._session_manager.update_session_fingerprint(
                        session_id, list(request.messages)
                    )
                except Exception as e:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            f"Failed to update session fingerprint: {e}", exc_info=True
                        )

            # Return backend response unchanged (Req 1.4)
            return backend_response
        finally:
            # Complete turn after response (or error) to update replacement state (Req 1.7)
            if self._replacement_service is not None:
                self._replacement_service.complete_turn(session_id)
