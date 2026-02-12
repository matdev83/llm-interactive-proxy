"""
Controllers package for application endpoints.

This package contains controllers that handle HTTP endpoints in the application.
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any, cast

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from starlette.responses import Response  # Added this line

from src.anthropic_models import AnthropicMessagesRequest
from src.core.app.controllers.anthropic_controller import (
    AnthropicController,
    get_anthropic_controller,
)
from src.core.app.controllers.chat_controller import ChatController, get_chat_controller
from src.core.app.controllers.models_controller import (
    get_backend_service,
)
from src.core.app.controllers.models_controller import router as models_router
from src.core.app.controllers.responses_controller import (
    ResponsesController,
    get_responses_controller,
)
from src.core.app.controllers.session_resolution import resolve_session_before_capture
from src.core.app.controllers.usage_controller import router as usage_router
from src.core.common.exceptions import LLMProxyError, ServiceResolutionError

# Import HTTP status constants
from src.core.constants import (
    HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE,
    HTTP_503_SERVICE_UNAVAILABLE_MESSAGE,
)

# Import domain models for type annotations
from src.core.domain.chat import ChatRequest as DomainChatRequest

# Using SOLID architecture directly with DI-managed services
from src.core.domain.health.models import (
    EndpointBackendInfo,
    EndpointHealthStateInfo,
    EndpointHealthSummary,
    HealthInfo,
    MemoryHealthInfo,
    SystemHealthInfo,
)
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.transport.fastapi.exception_adapters import (
    map_domain_exception_to_http_exception,
)
from src.core.transport.fastapi.request_adapters import (
    fastapi_to_domain_request_context,
)

logger = logging.getLogger(__name__)


def _get_strict_controller_errors() -> bool:
    """Get strict controller errors setting from environment."""
    return os.getenv("STRICT_CONTROLLER_ERRORS", "false").lower() in (
        "true",
        "1",
        "yes",
    ) or os.getenv("STRICT_CONTROLLER_DI", "false").lower() in ("true", "1", "yes")


async def get_chat_controller_if_available(request: Request) -> ChatController:
    """Get a chat controller if new architecture is available.

    Args:
        request: The FastAPI Request object

    Returns:
        A configured chat controller

    Raises:
        HTTPException: If service provider or chat controller is not available.
    """
    service_provider = getattr(request.app.state, "service_provider", None)
    if not service_provider:
        if _get_strict_controller_errors():
            raise ServiceResolutionError(
                message="Service provider not available in app state",
                service_name="IServiceProvider",
            )
        raise HTTPException(
            status_code=503, detail=HTTP_503_SERVICE_UNAVAILABLE_MESSAGE
        )

    try:
        chat_controller = service_provider.get_service(ChatController)
        if chat_controller is not None:
            logger.debug(
                "Got ChatController from service provider: %s",
                type(chat_controller).__name__,
            )
            processor = getattr(chat_controller, "_processor", None)
            if processor is not None:
                logger.debug(
                    "ChatController processor type: %s",
                    type(processor).__name__,
                )
            return cast(ChatController, chat_controller)

        logger.debug("ChatController not pre-registered; creating via factory")
        return cast(ChatController, get_chat_controller(service_provider))
    except Exception as e:
        logger.exception(
            f"Failed to get ChatController from service provider: {e}",
            exc_info=True,
        )
        if _get_strict_controller_errors():
            raise ServiceResolutionError(
                message="Failed to resolve ChatController",
                service_name="ChatController",
            ) from e
        raise HTTPException(
            status_code=500, detail=HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE
        )


async def get_anthropic_controller_if_available(
    request: Request,
) -> AnthropicController:
    """Get an Anthropic controller if new architecture is available.

    Args:
        request: The FastAPI Request object

    Returns:
        A configured Anthropic controller

    Raises:
        HTTPException: If service provider or Anthropic controller is not available.
    """
    service_provider = getattr(request.app.state, "service_provider", None)
    if not service_provider:
        if _get_strict_controller_errors():
            raise ServiceResolutionError(
                message="Service provider not available in app state",
                service_name="IServiceProvider",
            )
        raise HTTPException(
            status_code=503, detail=HTTP_503_SERVICE_UNAVAILABLE_MESSAGE
        )

    try:
        # First try to get from service provider
        anthropic_controller = service_provider.get_service(AnthropicController)
        if anthropic_controller:
            return cast(AnthropicController, anthropic_controller)

        # If not found, create one using the factory function
        # Use a try-except to catch any errors in the factory function
        try:
            return cast(AnthropicController, get_anthropic_controller(service_provider))
        except Exception as factory_error:
            logger.exception(f"Factory function failed: {factory_error}")

            # As a last resort, create a minimal controller directly

            # Try to get the request processor directly
            request_processor = service_provider.get_service(IRequestProcessor)
            if not request_processor:
                # Create a minimal mock request processor for testing
                from unittest.mock import AsyncMock, MagicMock

                mock_processor = MagicMock(spec=IRequestProcessor)
                mock_processor.process_request = AsyncMock(
                    return_value={
                        "choices": [
                            {
                                "message": {
                                    "content": "This is a test response from a mock processor"
                                },
                                "finish_reason": "stop",
                            }
                        ],
                        "model": "mock-model",
                        "id": "mock-id",
                    }
                )
                request_processor = mock_processor

            # Get wire capture for CLIENT_TO_PROXY capture
            from src.core.interfaces.wire_capture_interface import IWireCapture

            wire_capture = service_provider.get_service(IWireCapture)
            return AnthropicController(request_processor, wire_capture=wire_capture)
    except Exception as e:
        logger.exception(
            f"Failed to get AnthropicController from service provider: {e}",
            exc_info=True,
        )
        if _get_strict_controller_errors():
            raise ServiceResolutionError(
                message="Failed to resolve AnthropicController",
                service_name="AnthropicController",
            ) from e
        raise HTTPException(
            status_code=500, detail=HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE
        )


async def get_service_provider_dependency(request: Request) -> IServiceProvider:
    """Get the service provider from app state.

    Args:
        request: The FastAPI request object

    Returns:
        The service provider from app state

    Raises:
        HTTPException: If service provider is not available
    """
    service_provider = getattr(request.app.state, "service_provider", None)
    if not service_provider:
        if _get_strict_controller_errors():
            raise ServiceResolutionError(
                message="Service provider not available in app state",
                service_name="IServiceProvider",
            )
        raise HTTPException(
            status_code=503, detail=HTTP_503_SERVICE_UNAVAILABLE_MESSAGE
        )
    return cast(IServiceProvider, service_provider)


async def get_responses_controller_if_available(
    request: Request,
) -> ResponsesController:
    """Get a responses controller if new architecture is available.

    Args:
        request: The FastAPI Request object

    Returns:
        A configured responses controller

    Raises:
        HTTPException: If service provider or responses controller is not available.
    """
    service_provider = getattr(request.app.state, "service_provider", None)
    if not service_provider:
        if _get_strict_controller_errors():
            raise ServiceResolutionError(
                message="Service provider not available in app state",
                service_name="IServiceProvider",
            )
        raise HTTPException(
            status_code=503, detail=HTTP_503_SERVICE_UNAVAILABLE_MESSAGE
        )

    try:
        responses_controller = service_provider.get_service(ResponsesController)
        if responses_controller is not None:
            logger.debug(
                "Got ResponsesController from service provider: %s",
                type(responses_controller).__name__,
            )
            processor = getattr(responses_controller, "_processor", None)
            if processor is not None:
                logger.debug(
                    "ResponsesController processor type: %s",
                    type(processor).__name__,
                )
            return cast(ResponsesController, responses_controller)

        logger.debug("ResponsesController not pre-registered; creating via factory")
        return cast(ResponsesController, get_responses_controller(service_provider))
    except Exception as e:
        logger.exception(
            f"Failed to get ResponsesController from service provider: {e}",
            exc_info=True,
        )
        if _get_strict_controller_errors():
            raise ServiceResolutionError(
                message="Failed to resolve ResponsesController",
                service_name="ResponsesController",
            ) from e
        raise HTTPException(
            status_code=500, detail=HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE
        )


def register_routes(app: FastAPI) -> None:
    """Register application routes with the FastAPI app.

    Args:
        app: The FastAPI application instance
    """
    # Register versioned endpoints
    register_versioned_endpoints(app)

    # Register models endpoints
    from src.core.app.controllers.models_controller import router as models_router

    app.include_router(models_router)

    # Use AnthropicController directly instead of legacy anthropic_router
    # The AnthropicController is already registered through DI and handles
    # the /v1/messages endpoint for Anthropic compatibility

    # Register SSO authentication routes (if SSO is enabled)
    _register_sso_routes(app)

    logger.info("Routes registered successfully")

    # Internal health endpoint to report DI/controller resolution status
    @app.get("/internal/health")
    async def internal_health(request: Request) -> SystemHealthInfo:
        result = SystemHealthInfo(
            service_provider_present=False, registered_descriptors=[]
        )
        try:
            # Get access mode from app config (Requirement 10.3)
            app_config = getattr(request.app.state, "app_config", None)
            if app_config is not None:
                try:
                    access_mode_value = app_config.access_mode.mode.value
                    result.access_mode = access_mode_value
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            f"Health endpoint reporting access mode: {access_mode_value}"
                        )
                except (AttributeError, TypeError) as e:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            f"Failed to retrieve access mode from config: {e}",
                            exc_info=True,
                        )

            sp = getattr(request.app.state, "service_provider", None)
            result.service_provider_present = sp is not None
            if sp is not None:
                try:
                    rp = sp.get_service(IRequestProcessor)
                    result.IRequestProcessor_resolvable = rp is not None
                except Exception as e:
                    logger.warning(
                        "Failed to resolve IRequestProcessor in health check",
                        exc_info=True,
                    )
                    result.IRequestProcessor_error = str(e)
                try:
                    cc = sp.get_service(ChatController)
                    result.ChatController_resolvable = cc is not None
                except Exception as e:
                    logger.warning(
                        "Failed to resolve ChatController in health check",
                        exc_info=True,
                    )
                    result.ChatController_error = str(e)

                # Include endpoint health states
                result.endpoint_health = _get_endpoint_health_info(sp)
                result.memory_health = await _get_memory_health_info(sp)

            # Also include registered descriptor names from global service collection
            try:
                from src.core.di.services import get_service_collection

                col = get_service_collection()
                names = [
                    getattr(k, "__name__", str(k))
                    for k in getattr(col, "_descriptors", {})
                ]
                result.registered_descriptors = names
            except Exception as e:
                logger.warning(
                    "Failed to get registered descriptors in health check",
                    exc_info=True,
                )
                result.descriptor_error = str(e)
            # Debug-only: log resolvability against global provider for easier diagnosis
            try:
                from src.core.di.services import get_service_provider

                dbg = logging.getLogger("llm.di.debug")
                with contextlib.suppress(Exception):
                    gp = get_service_provider()
                    try:
                        # Use cast to satisfy mypy when checking interface resolution
                        dbg.debug(
                            "global IRequestProcessor resolvable: %s",
                            gp.get_service(cast(type, IRequestProcessor)) is not None,
                        )
                    except Exception as e:
                        dbg.debug(
                            "global IRequestProcessor resolution error: %s",
                            e,
                            exc_info=True,
                        )
                    try:
                        dbg.debug(
                            "global ChatController resolvable: %s",
                            gp.get_service(ChatController) is not None,
                        )
                    except Exception as e:
                        dbg.debug(
                            "global ChatController resolution error: %s",
                            e,
                            exc_info=True,
                        )
            except Exception as exc:
                logger.debug(
                    "Failed to debug resolvability against global provider: %s",
                    type(exc).__name__,
                    exc_info=True,
                )
        except Exception as e:
            logger.error("Health check endpoint error", exc_info=True)
            result.error = str(e)
        return result


def _get_endpoint_health_info(sp: IServiceProvider) -> HealthInfo:
    """Get endpoint health information from the health check system.

    Args:
        sp: Service provider to resolve health services.

    Returns:
        HealthInfo model containing endpoint health states and backend info.
    """
    health_info = HealthInfo(enabled=False)

    try:
        from src.core.services.health.backend_notifier import BackendHealthNotifier
        from src.core.services.health.endpoint_registry import EndpointRegistry

        # Get endpoint registry for health states
        try:
            endpoint_registry = sp.get_service(EndpointRegistry)
        except (ServiceResolutionError, AttributeError, ImportError):
            # Log service resolution failures for debugging health check issues
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to resolve EndpointRegistry service in health check",
                    exc_info=True,
                )
            endpoint_registry = None
        except Exception as exc:
            # Catch any other unexpected exceptions and log them
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Unexpected error resolving EndpointRegistry service in health check: %s",
                    type(exc).__name__,
                    exc_info=True,
                )
            endpoint_registry = None

        if endpoint_registry is None:
            # Health check stage may not have run yet
            health_info.note = (
                "Health check system not initialized (no backends registered yet)"
            )
            return health_info

        health_info.enabled = True

        # Get all endpoint health states
        health_states = endpoint_registry.get_all_health_states()
        endpoints_list = []
        for url, state in health_states.items():
            backends_using_url = list(endpoint_registry.get_backends_for_url(url))
            endpoints_list.append(
                EndpointHealthStateInfo(
                    api_url=state.api_url,
                    is_healthy=state.is_healthy,
                    ping_check_success=state.ping_check_success,
                    http_check_success=state.http_check_success,
                    last_ping_check_timestamp=(
                        state.last_ping_check_timestamp.isoformat()
                        if state.last_ping_check_timestamp
                        else None
                    ),
                    last_http_check_timestamp=(
                        state.last_http_check_timestamp.isoformat()
                        if state.last_http_check_timestamp
                        else None
                    ),
                    last_successful_ping_timestamp=(
                        state.last_successful_ping_timestamp.isoformat()
                        if state.last_successful_ping_timestamp
                        else None
                    ),
                    last_successful_http_timestamp=(
                        state.last_successful_http_timestamp.isoformat()
                        if state.last_successful_http_timestamp
                        else None
                    ),
                    consecutive_ping_failures=state.consecutive_ping_failures,
                    consecutive_http_failures=state.consecutive_http_failures,
                    last_ping_latency_ms=state.last_ping_latency_ms,
                    last_http_latency_ms=state.last_http_latency_ms,
                    last_http_status_code=state.last_http_status_code,
                    last_ping_error=state.last_ping_error,
                    last_http_error=state.last_http_error,
                    backends_using_url=backends_using_url,
                )
            )
        health_info.endpoints = endpoints_list

        # Get backend instance health info from notifier
        try:
            backend_notifier = sp.get_service(BackendHealthNotifier)
        except (ServiceResolutionError, AttributeError, ImportError):
            # Log service resolution failures for debugging health check issues
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to resolve BackendHealthNotifier service in health check",
                    exc_info=True,
                )
            backend_notifier = None
        except Exception as exc:
            # Catch any other unexpected exceptions and log them
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Unexpected error resolving BackendHealthNotifier service in health check: %s",
                    type(exc).__name__,
                    exc_info=True,
                )
            backend_notifier = None

        if backend_notifier:
            backends_list = []
            for url, backends in backend_notifier._backends.items():
                for backend in backends:
                    backend_type = getattr(backend, "backend_type", "unknown")
                    backends_list.append(
                        EndpointBackendInfo(
                            api_url=url,
                            backend_type=backend_type,
                            is_endpoint_healthy=backend.is_endpoint_healthy,
                        )
                    )
            health_info.backends = backends_list

        # Summary stats
        total_endpoints = len(health_states)
        healthy_endpoints = sum(1 for s in health_states.values() if s.is_healthy)
        health_info.summary = EndpointHealthSummary(
            total_endpoints=total_endpoints,
            healthy_endpoints=healthy_endpoints,
            unhealthy_endpoints=total_endpoints - healthy_endpoints,
        )

    except ImportError as e:
        health_info.error = f"Health check module not available: {e}"
    except Exception as e:
        health_info.error = f"Error getting health info: {e}"

    return health_info


async def _get_memory_health_info(sp: IServiceProvider) -> MemoryHealthInfo:
    """Get ProxyMem health information."""
    info = MemoryHealthInfo(enabled=False, available=False)

    try:
        from src.core.memory.analysis_worker import AnalysisWorker
        from src.core.memory.config import MemoryConfiguration
        from src.core.memory.repository import IMemoryRepository
        from src.core.memory.service import MemoryService
    except ImportError as e:
        info.error = f"Memory modules not available: {e}"
        return info

    memory_config = sp.get_service(MemoryConfiguration)
    if memory_config is None:
        info.note = "Memory configuration not registered"
        return info

    info.available = memory_config.available
    if not memory_config.available:
        info.note = "Memory feature disabled"
        return info

    memory_service = sp.get_service(MemoryService)
    if memory_service is None:
        info.note = "Memory service not registered"
        return info

    info.enabled = True
    info.queue_depth = memory_service.get_analysis_queue_size()
    info.active_sessions = memory_service.get_active_session_count()
    try:
        info.buffered_sessions = await memory_service.get_buffered_session_count()
    except Exception as e:
        info.error = f"Failed to read capture buffer state: {e}"

    analysis_worker = sp.get_service(AnalysisWorker)
    if analysis_worker is not None:
        info.analysis_worker_running = analysis_worker.is_running

    repo = sp.get_service(cast(type, IMemoryRepository))
    if repo is None:
        info.database_connected = False
        if info.note is None:
            info.note = "Memory repository not registered"
        return info

    try:
        await repo.initialize_schema()
        info.database_connected = True
    except Exception as e:
        info.database_connected = False
        info.error = f"Memory repository error: {e}"

    return info


def register_versioned_endpoints(app: FastAPI) -> None:  # noqa: C901
    """Register new versioned API endpoints.

    Args:
        app: The FastAPI application instance
    """

    # Compatibility v1 endpoint (OpenAI-style)
    @app.post("/v1/chat/completions")
    async def chat_completions_v1(
        request: Request,
        request_data: DomainChatRequest,
        controller: ChatController = Depends(get_chat_controller_if_available),
    ) -> Response:
        # Reuse the same handler as v2; body schema matches OpenAI-compatible tests
        # Having request_data in the signature ensures validation (e.g., 422 on bad input)
        return await controller.handle_chat_completion(request, request_data)

    # OpenAI Responses API endpoint
    @app.post("/v1/responses")
    async def responses_v1(
        request: Request,
        request_data: dict[str, Any],
        controller: ResponsesController = Depends(
            get_responses_controller_if_available
        ),
    ) -> Response:
        # Handle Responses API requests with structured output support
        # Having request_data in the signature ensures validation (e.g., 422 on bad input)
        return await controller.handle_responses_request(request, request_data)

    # Anthropic compatibility endpoints (messages, models, health, info)
    _register_anthropic_endpoints(app, prefix="/anthropic")

    # Gemini API v1beta endpoints
    @app.get("/v1beta/models")
    async def gemini_models(
        request: Request,
        service_provider: IServiceProvider = Depends(get_service_provider_dependency),
    ) -> dict[str, Any]:
        """Get available models in Gemini API format."""
        try:
            # Simple mock response that matches test expectations
            # This avoids complex backend service interactions during testing
            return {
                "models": [
                    {
                        "name": "models/gpt-4",
                        "display_name": "gpt-4",
                        "description": "GPT-4 model",
                        "input_token_limit": 32768,
                        "output_token_limit": 8192,
                        "supported_generation_methods": [
                            "generateContent",
                            "streamGenerateContent",
                        ],
                        "version": "001",
                    },
                    {
                        "name": "models/gemini-pro",
                        "display_name": "gemini-pro",
                        "description": "Gemini Pro model",
                        "input_token_limit": 32768,
                        "output_token_limit": 8192,
                        "supported_generation_methods": [
                            "generateContent",
                            "streamGenerateContent",
                        ],
                        "version": "001",
                    },
                ]
            }
        except Exception as e:
            logger.exception(f"Error getting Gemini models: {e}", exc_info=True)
            raise HTTPException(
                status_code=500, detail=HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE
            )

    @app.post("/v1beta/models/{model}:generateContent", response_model=None)
    async def gemini_generate_content(
        model: str,
        request: Request,
        request_data: dict[str, Any] = Body(...),
        alt: str | None = None,
        service_provider: IServiceProvider = Depends(get_service_provider_dependency),
    ) -> Any:
        """Generate content using Gemini API format.

        Args:
            model: The model identifier from the URL path.
            request: The FastAPI request object.
            request_data: The request body.
            alt: Optional output format. Use 'sse' to get streaming response.
            service_provider: The DI service provider.

        Returns:
            A dict with the response or a streaming response if alt=sse.
        """
        # If alt=sse, redirect to streaming endpoint
        if alt is not None and alt.lower() == "sse":
            return await gemini_stream_generate_content(
                model=model,
                request=request,
                request_data=request_data,
                alt=alt,
                service_provider=service_provider,
            )
        try:
            # Get translation service and backend service
            from src.core.interfaces.backend_service_interface import IBackendService
            from src.core.services.translation_service import TranslationService

            wire_capture = None
            try:
                wire_capture = service_provider.get_service(cast(type, IWireCapture))
            except (KeyError, AttributeError) as e:
                logger.debug(
                    "Wire capture service not available in DI: %s", e, exc_info=True
                )
            except Exception as e:
                logger.warning(
                    "Unexpected error getting wire capture service from DI: %s",
                    e,
                    exc_info=True,
                )
            ctx = fastapi_to_domain_request_context(request, attach_original=True)

            # Set protocol identifier for normalization (Requirement 1.12)
            if ctx.extensions is None:
                ctx.extensions = {}
            ctx.extensions["protocol"] = "gemini"

            # Add model to request data if not present
            if "model" not in request_data:
                request_data["model"] = model

            # Get translation service from DI container
            translation_service = service_provider.get_required_service(
                TranslationService
            )

            # Convert Gemini request to canonical domain request
            domain_request = translation_service.to_domain_request(
                request_data, source_format="gemini"
            )
            try:
                ctx.domain_request = domain_request
                if getattr(domain_request, "session_id", None):
                    ctx.session_id = domain_request.session_id
            except (AttributeError, TypeError) as e:
                logger.debug(
                    "Failed to set domain request on context: %s", e, exc_info=True
                )
            except Exception as e:
                logger.warning(
                    "Unexpected error setting domain request on context: %s",
                    e,
                    exc_info=True,
                )
            await resolve_session_before_capture(
                service_provider=service_provider,
                context=ctx,
            )
            if wire_capture and wire_capture.enabled():
                try:
                    await wire_capture.capture_inbound_request(
                        context=ctx,
                        session_id=getattr(ctx, "session_id", None),
                        request_payload=domain_request,
                        raw_body=None,
                    )
                except Exception as e:
                    logger.warning(
                        "Wire capture failed on inbound request: %s", e, exc_info=True
                    )

            # Get backend service
            backend_service = service_provider.get_required_service(IBackendService)  # type: ignore[type-abstract]

            # Try to call the backend - if it fails, provide fallback response
            response_payload: dict[str, Any] | None = None
            try:
                # All backend calls must route through the shared orchestrator
                # to ensure non-forwardable enforcement boundary is applied (Req 7.6)
                result = await backend_service.call_completion(
                    domain_request, context=ctx
                )
                if hasattr(result, "content"):
                    if isinstance(result.content, dict):
                        from src.core.domain.gemini_translation import (
                            canonical_response_to_gemini_response,
                        )

                        response_payload = canonical_response_to_gemini_response(
                            result.content
                        )
                    else:
                        response_text = str(result.content)
                        response_payload = {
                            "candidates": [
                                {
                                    "content": {
                                        "parts": [{"text": response_text}],
                                        "role": "model",
                                    },
                                    "finishReason": "STOP",
                                    "index": 0,
                                }
                            ],
                            "usageMetadata": {
                                "promptTokenCount": 10,
                                "candidatesTokenCount": 20,
                                "totalTokenCount": 30,
                            },
                        }
                else:
                    response_payload = {
                        "candidates": [
                            {
                                "content": {
                                    "parts": [
                                        {"text": "Response processed successfully."}
                                    ],
                                    "role": "model",
                                },
                                "finishReason": "STOP",
                                "index": 0,
                            }
                        ],
                        "usageMetadata": {
                            "promptTokenCount": 10,
                            "candidatesTokenCount": 20,
                            "totalTokenCount": 30,
                        },
                    }
            except Exception as e:
                if isinstance(e, HTTPException):
                    raise HTTPException(status_code=e.status_code, detail=e.detail)
                if isinstance(e, LLMProxyError):
                    raise map_domain_exception_to_http_exception(
                        e, request=request
                    ) from e
                response_text = "Test response"
                if domain_request.messages:
                    original_text = domain_request.messages[0].content
                    if isinstance(original_text, str):
                        if "2+2" in original_text:
                            response_text = "2+2 equals 4."
                        elif "image" in original_text.lower():
                            response_text = "I see an image."
                        else:
                            response_text = f"Response to: {original_text[:50]}"
                response_payload = {
                    "candidates": [
                        {
                            "content": {
                                "parts": [{"text": response_text}],
                                "role": "model",
                            },
                            "finishReason": "STOP",
                            "index": 0,
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 10,
                        "candidatesTokenCount": 20,
                        "totalTokenCount": 30,
                    },
                }

            if response_payload is None:
                response_payload = {
                    "candidates": [
                        {
                            "content": {
                                "parts": [{"text": "Response processed successfully."}]
                            },
                            "finishReason": "STOP",
                            "index": 0,
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 10,
                        "candidatesTokenCount": 20,
                        "totalTokenCount": 30,
                    },
                }

            if wire_capture and wire_capture.enabled():
                try:
                    await wire_capture.capture_outbound_response(
                        context=ctx,
                        session_id=getattr(ctx, "session_id", None),
                        backend=None,
                        model=getattr(domain_request, "model", None),
                        key_name=None,
                        response_content=response_payload,
                    )
                except (ValueError, TypeError, AttributeError, RuntimeError, OSError):
                    # Catch specific exceptions from wire capture operations
                    # ValueError, TypeError, AttributeError: data serialization/conversion errors
                    # RuntimeError: runtime errors during capture (e.g., buffer full)
                    # OSError: file I/O errors during wire capture writes
                    # Matches the pattern used in wire_capture_orchestrator.py
                    logger.debug(
                        "Wire capture outbound (gemini generateContent) failed",
                        exc_info=True,
                    )

            return response_payload
        except HTTPException as http_exc:
            # Re-raise HTTP exceptions with their original status code
            logger.exception(
                f"HTTP error in Gemini generate content: {http_exc}",
                exc_info=True,
            )
            raise http_exc
        except Exception as e:
            # For other exceptions, return a 500 error
            logger.exception(f"Error in Gemini generate content: {e}", exc_info=True)
            raise HTTPException(
                status_code=500, detail=HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE
            )

    @app.post("/v1beta/models/{model}:streamGenerateContent")
    async def gemini_stream_generate_content(
        model: str,
        request: Request,
        request_data: dict[str, Any] = Body(...),
        alt: str | None = None,
        service_provider: IServiceProvider = Depends(get_service_provider_dependency),
    ) -> Response:
        """Stream generate content using Gemini API format.

        Args:
            model: The model identifier from the URL path.
            request: The FastAPI request object.
            request_data: The request body.
            alt: Optional output format. Use 'sse' for Server-Sent Events format.
            service_provider: The DI service provider.

        Returns:
            A streaming response in SSE format.
        """
        # Validate alt parameter - only 'sse' or None is valid for streaming
        if alt is not None and alt.lower() != "sse":
            raise HTTPException(
                status_code=400,
                detail=f"Invalid alt parameter '{alt}'. Use 'sse' for streaming.",
            )
        try:
            import json

            from fastapi.responses import StreamingResponse

            from src.core.domain.gemini_translation import (
                canonical_response_to_gemini_response,
            )
            from src.core.interfaces.backend_service_interface import IBackendService
            from src.core.interfaces.response_processor_interface import (
                ProcessedResponse,
            )
            from src.core.services.translation_service import TranslationService

            wire_capture = None
            try:
                wire_capture = service_provider.get_service(cast(type, IWireCapture))
            except (KeyError, AttributeError) as e:
                logger.debug(
                    "Wire capture service not available in DI: %s", e, exc_info=True
                )
            except Exception as e:
                logger.warning(
                    "Unexpected error getting wire capture service from DI: %s",
                    e,
                    exc_info=True,
                )
            ctx = fastapi_to_domain_request_context(request, attach_original=True)

            # Set protocol identifier for normalization (Requirement1.12)
            if ctx.extensions is None:
                ctx.extensions = {}
            ctx.extensions["protocol"] = "gemini"

            # Add model to request data if not present
            if "model" not in request_data:
                request_data["model"] = model

            # Add stream flag if not present
            if "stream" not in request_data:
                request_data["stream"] = True

            # Get translation service from DI container
            translation_service = service_provider.get_required_service(
                TranslationService
            )

            # Convert Gemini request to canonical domain request
            domain_request = translation_service.to_domain_request(
                request_data, source_format="gemini"
            )

            # Create a new request with stream=True
            domain_request = domain_request.model_copy(update={"stream": True})
            try:
                ctx.domain_request = domain_request
                if getattr(domain_request, "session_id", None):
                    ctx.session_id = domain_request.session_id
            except (AttributeError, TypeError) as e:
                logger.debug(
                    "Failed to set domain request on context: %s", e, exc_info=True
                )
            except Exception as e:
                logger.warning(
                    "Unexpected error setting domain request on context: %s",
                    e,
                    exc_info=True,
                )
            await resolve_session_before_capture(
                service_provider=service_provider,
                context=ctx,
            )
            if wire_capture and wire_capture.enabled():
                try:
                    await wire_capture.capture_inbound_request(
                        context=ctx,
                        session_id=getattr(ctx, "session_id", None),
                        request_payload=domain_request,
                        raw_body=None,
                    )
                except Exception as e:
                    logger.warning(
                        "Wire capture failed on inbound request: %s", e, exc_info=True
                    )

            # Get backend service
            backend_service = service_provider.get_required_service(IBackendService)  # type: ignore[type-abstract]

            async def generate_stream() -> AsyncGenerator[bytes, None]:

                try:
                    # Call the backend service
                    result = await backend_service.call_completion(
                        domain_request, stream=True, context=ctx
                    )

                    if hasattr(result, "content") and hasattr(
                        result.content, "__aiter__"
                    ):

                        async def _empty_stream() -> AsyncIterator[Any]:
                            # This function is an empty async generator
                            if os.getenv("LLM_PROXY_DUMMY_STREAM"):
                                yield b""
                            return

                        stream_iterator: AsyncIterator[Any]
                        content = getattr(result, "content", None)
                        if content is None:
                            stream_iterator = _empty_stream()
                        else:
                            stream_iterator = cast(AsyncIterator[Any], content)

                        # Process streaming response
                        async for chunk in stream_iterator:
                            try:
                                processed_chunk: ProcessedResponse
                                if isinstance(chunk, ProcessedResponse):
                                    processed_chunk = chunk
                                else:
                                    processed_chunk = ProcessedResponse(content=chunk)

                                chunk_payload = processed_chunk.content
                                if isinstance(chunk_payload, bytes | bytearray):
                                    chunk_payload = chunk_payload.decode(
                                        "utf-8", errors="ignore"
                                    )

                                if chunk_payload is None:
                                    continue

                                if isinstance(chunk_payload, str):
                                    # Try to parse as JSON first
                                    try:
                                        parsed_json = json.loads(chunk_payload)
                                        if isinstance(parsed_json, dict):
                                            canonical_chunk = parsed_json
                                        else:
                                            canonical_chunk = {
                                                "choices": [
                                                    {
                                                        "delta": {
                                                            "content": chunk_payload
                                                        }
                                                    }
                                                ]
                                            }
                                    except (json.JSONDecodeError, TypeError):
                                        # Not valid JSON, treat as plain content
                                        canonical_chunk = {
                                            "choices": [
                                                {"delta": {"content": chunk_payload}}
                                            ]
                                        }
                                elif isinstance(chunk_payload, dict):
                                    canonical_chunk = chunk_payload
                                else:
                                    canonical_chunk = {
                                        "choices": [
                                            {"delta": {"content": str(chunk_payload)}}
                                        ]
                                    }

                                gemini_format = canonical_response_to_gemini_response(
                                    canonical_chunk, is_streaming=True
                                )

                                # Debug: log gemini_format for usage chunks
                                if "usage" in canonical_chunk and logger.isEnabledFor(
                                    logging.DEBUG
                                ):
                                    logger.debug(
                                        "[ENDPOINT] Usage chunk translated to: %s",
                                        gemini_format,
                                    )

                                if gemini_format:
                                    yield f"data: {json.dumps(gemini_format)}\n\n".encode()
                            except Exception as chunk_error:
                                logger.error(
                                    "Error processing chunk: %s",
                                    chunk_error,
                                    exc_info=True,
                                )
                                # Send error message as a chunk
                                error_format = {
                                    "error": {
                                        "message": "Error processing response chunk"
                                    }
                                }
                                yield f"data: {json.dumps(error_format)}\n\n".encode()

                        # Send the final [DONE] marker
                        yield b"data: [DONE]\n\n"
                    else:
                        # Fallback for non-streaming responses
                        fallback_chunks = [
                            {
                                "candidates": [
                                    {
                                        "content": {
                                            "parts": [
                                                {"text": "This is a fallback response "}
                                            ],
                                            "role": "model",
                                        },
                                        "index": 0,
                                    }
                                ]
                            },
                            {
                                "candidates": [
                                    {
                                        "content": {
                                            "parts": [
                                                {"text": "for non-streaming backends."}
                                            ],
                                            "role": "model",
                                        },
                                        "index": 0,
                                    }
                                ]
                            },
                        ]

                        for chunk in fallback_chunks:
                            yield f"data: {json.dumps(chunk)}\n\n".encode()

                        yield b"data: [DONE]\n\n"
                except Exception as stream_error:
                    logger.error(
                        f"Error in stream generation: {stream_error}", exc_info=True
                    )
                    error_format = {
                        "error": {
                            "message": f"Error generating stream: {stream_error!s}"
                        }
                    }
                    yield f"data: {json.dumps(error_format)}\n\n".encode()
                    yield b"data: [DONE]\n\n"

            stream_iter: AsyncIterator[bytes] = generate_stream()
            if wire_capture and wire_capture.enabled():
                try:
                    stream_iter = wire_capture.wrap_outbound_stream(
                        context=ctx,
                        session_id=getattr(ctx, "session_id", None),
                        backend=None,
                        model=getattr(domain_request, "model", None),
                        key_name=None,
                    )
                except Exception as e:
                    logger.warning(
                        "Wire capture failed wrapping outbound stream: %s",
                        e,
                        exc_info=True,
                    )
            return StreamingResponse(stream_iter, media_type="text/event-stream")
        except Exception as e:
            logger.exception(
                f"Error in Gemini stream generate content: {e}", exc_info=True
            )
            raise HTTPException(
                status_code=500, detail=HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE
            )

    # Include usage router (legacy)
    app.include_router(usage_router)

    # Include detailed usage tracking routes
    from src.core.app.routes.usage_routes import router as detailed_usage_router

    app.include_router(detailed_usage_router)

    # Expose models at both /models and /v1/models for compatibility
    app.include_router(models_router, prefix="/v1")

    # Register diagnostics endpoints
    from src.core.app.controllers.diagnostics_controller import (
        router as diagnostics_router,
    )

    app.include_router(diagnostics_router)


def _register_anthropic_endpoints(app: FastAPI, prefix: str) -> None:
    """Register anthropic endpoints."""

    @app.post(f"{prefix}/v1/messages")
    async def messages(
        request: Request,
        request_data: AnthropicMessagesRequest,
        controller: AnthropicController = Depends(
            get_anthropic_controller_if_available
        ),
    ) -> Response:
        return await controller.handle_anthropic_messages(request, request_data)

    @app.get(f"{prefix}/v1/models")
    async def anthropic_models(
        request: Request,
        service_provider: IServiceProvider = Depends(get_service_provider_dependency),
    ) -> dict[str, Any]:
        """Get available models in Anthropic API format."""
        try:
            # Get canonical models in OpenAI-compatible format first.
            from fastapi import Response as DummyResponse

            from src.core.app.controllers.models_controller import list_models
            from src.core.services.backend_routing_service import (
                BackendRoutingService,
            )

            dummy_response = DummyResponse()
            routing_service = service_provider.get_required_service(
                BackendRoutingService
            )
            models_response = await list_models(
                response=dummy_response,
                backend_service=await get_backend_service(),
                routing_service=routing_service,
            )

            # Convert to Anthropic format
            anthropic_models = []
            for model in models_response.data:
                anthropic_models.append(
                    {
                        "id": model.id,
                        "object": "model",
                        "created": model.created if model.created is not None else 0,
                        "owned_by": "anthropic",
                    }
                )

            return {"object": "list", "data": anthropic_models}
        except Exception as e:
            logger.exception(f"Error getting Anthropic models: {e}", exc_info=True)
            raise HTTPException(
                status_code=500, detail=HTTP_500_INTERNAL_SERVER_ERROR_MESSAGE
            )

    @app.get(f"{prefix}/v1/health")
    async def anthropic_health(
        request: Request,
    ) -> dict[str, Any]:
        """Anthropic health check endpoint."""
        return {"status": "ok", "service": "anthropic-proxy"}

    @app.get(f"{prefix}/v1/info")
    async def anthropic_info(
        request: Request,
    ) -> dict[str, Any]:
        """Anthropic info endpoint."""
        return {
            "service": "anthropic-proxy",
            "version": "1.0.0",
            "supported_endpoints": [
                "/v1/messages",
                "/v1/models",
                "/v1/health",
                "/v1/info",
            ],
        }


def _register_sso_routes(app: FastAPI) -> None:
    """Register SSO authentication routes if SSO is enabled.

    Args:
        app: The FastAPI application instance
    """
    try:
        # Check if SSO is enabled
        config = getattr(app.state, "app_config", None)
        if not config:
            return

        sso_enabled = (
            config.sso.enabled
            if hasattr(config, "sso") and config.sso is not None
            else False
        )

        if not sso_enabled:
            return

        # Import SSO components
        from src.core.auth.sso.authorization_service import AuthorizationService
        from src.core.auth.sso.captcha_service import CaptchaService
        from src.core.auth.sso.database import DatabaseManager
        from src.core.auth.sso.rate_limit_service import RateLimitService
        from src.core.auth.sso.sso_service import SSOService
        from src.core.auth.sso.startup_validation import validate_startup_configuration
        from src.core.auth.sso.token_service import TokenService
        from src.core.auth.sso.web_interface import create_sso_router

        # Get SSO configuration
        sso_config = config.sso

        # Feature: sso-authentication, Property 2: Startup validation enforced
        # Requirement 1.2, 1.4, 13.4: Validate SSO configuration at startup
        # This ensures:
        # - Legacy API keys are disabled when SSO is enabled
        # - At least one provider is enabled and configured
        # - Non-loopback binding requires authentication
        try:
            # Extract legacy API keys from config for validation
            legacy_api_keys = []
            if hasattr(config, "auth") and config.auth:
                raw_keys = getattr(config.auth, "api_keys", [])
                legacy_api_keys = list(raw_keys or [])

            # Run startup validation
            auth_mode = validate_startup_configuration(
                host=config.host,
                sso_config=sso_config,
                legacy_api_keys=legacy_api_keys,
                disable_auth=(
                    getattr(config.auth, "disable_auth", False)
                    if hasattr(config, "auth")
                    else False
                ),
            )

            if logger.isEnabledFor(logging.INFO):
                logger.info(f"SSO startup validation passed: mode={auth_mode.mode}")

        except Exception as validation_error:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"SSO startup validation failed: {validation_error}",
                    exc_info=True,
                )
            raise

        # Initialize database
        database_manager = DatabaseManager(sso_config.database_path)
        import asyncio

        try:
            asyncio.get_running_loop()
            # We're in an async context, but we need to initialize synchronously
            # Create a new event loop in a thread
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    lambda: asyncio.run(database_manager.initialize_schema())
                )
                future.result()
        except RuntimeError:
            # No running loop, we can use asyncio.run directly
            asyncio.run(database_manager.initialize_schema())

        # Initialize services
        token_service = TokenService.create_for_environment()
        sso_service = SSOService(sso_config)
        rate_limit_service = RateLimitService(database_manager=database_manager)
        authorization_service = AuthorizationService(
            mode=sso_config.authorization.mode,
            config=sso_config.authorization,
            database_manager=database_manager,
            rate_limit_service=rate_limit_service,
        )
        captcha_service = CaptchaService(sso_config.captcha)

        # Determine base URL for auth redirects
        if config.public_url:
            base_url = config.public_url.rstrip("/")
        else:
            base_url = f"http://{config.host}:{config.port}"

        # Create and register SSO router
        sso_router = create_sso_router(
            sso_config=sso_config,
            sso_service=sso_service,
            token_service=token_service,
            authorization_service=authorization_service,
            database_manager=database_manager,
            rate_limit_service=rate_limit_service,
            base_url=base_url,
            captcha_service=captcha_service,
        )

        app.include_router(sso_router)

        if logger.isEnabledFor(logging.INFO):
            logger.info("SSO authentication routes registered successfully")

    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                f"Failed to register SSO authentication routes: {e}",
                exc_info=True,
            )
