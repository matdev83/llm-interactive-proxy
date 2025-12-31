"""
ASGI wrapper for AssessmentMiddleware to make it compatible with FastAPI/Starlette.

This wrapper adapts AssessmentMiddleware to ASGI protocol required by FastAPI.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from fastapi import Request, Response
from src.core.app.middleware.assessment_middleware import AssessmentMiddleware
from src.core.common.exceptions import LLMProxyError
from src.core.domain.configuration.assessment_config import AssessmentConfig
from src.core.interfaces.assessment_service_interface import (
    IAssessmentService,
    ITurnCounterService,
)
from src.core.interfaces.non_forwardable_interface import (
    INonForwardableMessageIdentityService,
    INonForwardableMessageRegistry,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from fastapi import FastAPI


class AssessmentMiddlewareASGIWrapper:
    """
    ASGI wrapper for AssessmentMiddleware to make it compatible with FastAPI/Starlette.

    This wrapper adapts the AssessmentMiddleware to the ASGI protocol required by FastAPI.
    It receives the required services during initialization and creates an AssessmentMiddleware
    instance for each request.
    """

    def __init__(
        self,
        assessment_service: IAssessmentService,
        turn_counter_service: ITurnCounterService,
        config: AssessmentConfig,
        non_forwardable_registry: INonForwardableMessageRegistry | None = None,
        non_forwardable_identity_service: (
            INonForwardableMessageIdentityService | None
        ) = None,
    ):
        """
        Initialize the ASGI wrapper with required services.

        Args:
            assessment_service: Service for performing assessments
            turn_counter_service: Service for turn counting and timing
            config: Assessment configuration
            non_forwardable_registry: Optional registry for tagging non-forwardable messages
            non_forwardable_identity_service: Optional service for computing message identities
        """
        self.assessment_middleware = AssessmentMiddleware(
            assessment_service=assessment_service,
            turn_counter_service=turn_counter_service,
            config=config,
            non_forwardable_registry=non_forwardable_registry,
            non_forwardable_identity_service=non_forwardable_identity_service,
        )

    async def __call__(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """
        Process a request through the assessment middleware.

        Args:
            request: The incoming request
            call_next: The next middleware or endpoint handler

        Returns:
            The processed response
        """
        # Convert FastAPI Request to ChatRequest for the assessment middleware
        # This is a simplified approach - in a real implementation, you might need
        # to extract the ChatRequest from request state or convert properly
        try:
            # Process the request through assessment middleware
            # Since the original AssessmentMiddleware.process method expects a ChatRequest,
            # we need to adapt the FastAPI request to the expected format
            if hasattr(request.state, "chat_request") and request.state.chat_request:
                chat_request = request.state.chat_request
                processed_chat_request = await self.assessment_middleware.process(
                    chat_request
                )
                # Update the request state with the processed chat request
                request.state.chat_request = processed_chat_request
        except asyncio.CancelledError:
            # Propagate cancellation - don't swallow it
            raise
        except (AttributeError, TypeError, LLMProxyError) as e:
            # Expected errors during request processing:
            # - AttributeError: request.state attribute access failures
            # - TypeError: Type mismatches in request conversion
            # - LLMProxyError: Known proxy errors from assessment services
            # Log the error but continue with the original request (graceful degradation)
            logger.warning(
                "Assessment middleware processing error (continuing with original request): %s",
                e,
                exc_info=True,
            )
        except Exception as e:
            # Unexpected errors - log at error level for debugging
            # Continue with the original request to avoid breaking the request pipeline
            logger.error(
                "Unexpected error in assessment middleware (continuing with original request): %s",
                e,
                exc_info=True,
            )

        # Call the next middleware or endpoint with the request
        response = await call_next(request)
        return response


def add_assessment_middleware(
    app: "FastAPI",
    assessment_service: IAssessmentService,
    turn_counter_service: ITurnCounterService,
    config: AssessmentConfig,
    non_forwardable_registry: INonForwardableMessageRegistry | None = None,
    non_forwardable_identity_service: (
        INonForwardableMessageIdentityService | None
    ) = None,
) -> None:
    """
    Add assessment middleware to a FastAPI application.

    Args:
        app: The FastAPI application
        assessment_service: Service for performing assessments
        turn_counter_service: Service for turn counting and timing
        config: Assessment configuration
        non_forwardable_registry: Optional registry for tagging non-forwardable messages
        non_forwardable_identity_service: Optional service for computing message identities
    """
    from fastapi import FastAPI

    if not isinstance(app, FastAPI):
        raise TypeError("app must be a FastAPI instance")

    middleware_wrapper = AssessmentMiddlewareASGIWrapper(
        assessment_service=assessment_service,
        turn_counter_service=turn_counter_service,
        config=config,
        non_forwardable_registry=non_forwardable_registry,
        non_forwardable_identity_service=non_forwardable_identity_service,
    )

    # Register the middleware using FastAPI's decorator
    app.middleware("http")(middleware_wrapper.__call__)
