from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from src.core.app.middleware.loop_prevention_middleware import LoopPreventionMiddleware
from src.core.common.logging_utils import get_logger
from src.core.security import APIKeyMiddleware, AuthMiddleware
from src.request_middleware import CustomHeaderMiddleware
from src.response_middleware import RetryAfterMiddleware

logger = get_logger(__name__)


def configure_middleware(app: FastAPI, config: Any) -> None:
    """Configure middleware for the application.

    Args:
        app: The FastAPI application
        config: The application configuration (AppConfig or dict)
    """
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Allows all origins
        allow_credentials=True,
        allow_methods=["*"],  # Allows all methods
        allow_headers=["*"],  # Allows all headers
    )

    # Security headers middleware - adds X-Content-Type-Options, Cache-Control,
    # CSP (for HTML), X-Frame-Options (for HTML), etc.
    try:
        from src.core.app.middleware.security_headers_middleware import (
            add_security_headers_middleware,
        )

        add_security_headers_middleware(app)
        if logger.isEnabledFor(logging.INFO):
            logger.info("Security headers middleware is enabled")
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Failed to register SecurityHeadersMiddleware: %s", e, exc_info=True
            )

    # Check if SSO is enabled (used later to disable legacy auth)
    sso_enabled = (
        config.sso.enabled
        if hasattr(config, "sso") and config.sso is not None
        else False
    )

    # API key authentication middleware (if enabled)
    # New AppConfig object
    if hasattr(config, "auth"):
        auth_config = config.auth
        disable_auth = getattr(auth_config, "disable_auth", False)
        raw_api_keys = getattr(auth_config, "api_keys", [])
        raw_trusted_ips = getattr(auth_config, "trusted_ips", [])
    else:
        auth_config = None
        disable_auth = False
        raw_api_keys = []
        raw_trusted_ips = []

    # Ensure API keys and trusted IPs are always sequences before using them.
    # This avoids TypeErrors when a configuration provides ``None`` (common when
    # values are omitted in environment overrides) and keeps compatibility with
    # DI provided config objects that may return tuples or other iterables.
    api_keys = list(raw_api_keys or [])
    trusted_ips = list(raw_trusted_ips or [])
    brute_force_config = getattr(auth_config, "brute_force_protection", None)

    # Respect environment override for disabling auth (useful for tests)
    env_disable = os.getenv("DISABLE_AUTH", "").lower() == "true"
    disable_auth = disable_auth or env_disable

    # Feature: sso-authentication, Property 1: Legacy auth disabled when SSO enabled
    # Requirement 1.2: WHEN SSO mode is enabled THEN the Proxy SHALL disable the
    # legacy static Bearer key authentication mechanism.
    if sso_enabled and not disable_auth:
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "SSO authentication is enabled - legacy API key/token authentication is disabled"
            )
        disable_auth = True  # Force disable legacy auth when SSO is active

    if not disable_auth:
        # SECURITY: Removed test detection - production code should never detect test environment
        # If no API keys are provided, authentication will fail with clear error messages
        # This prevents unauthorized access and maintains security boundaries
        if logger.isEnabledFor(logging.INFO):
            logger.info("API Key authentication is enabled", key_count=len(api_keys))
        # Add API Key middleware
        brute_force_kwargs = (
            {
                "brute_force_enabled": getattr(brute_force_config, "enabled", True),
                "brute_force_ttl_seconds": getattr(
                    brute_force_config, "ttl_seconds", 900
                ),
                "brute_force_max_attempts": getattr(
                    brute_force_config, "max_failed_attempts", 5
                ),
                "brute_force_initial_block_seconds": getattr(
                    brute_force_config, "initial_block_seconds", 30
                ),
                "brute_force_block_multiplier": getattr(
                    brute_force_config, "block_multiplier", 2.0
                ),
                "brute_force_max_block_seconds": getattr(
                    brute_force_config, "max_block_seconds", 3600
                ),
            }
            if brute_force_config is not None
            else {}
        )
        app.add_middleware(
            APIKeyMiddleware,
            valid_keys=api_keys,
            trusted_ips=trusted_ips,
            **brute_force_kwargs,  # type: ignore[arg-type]
        )
    else:
        if logger.isEnabledFor(logging.INFO):
            logger.info("API Key authentication is disabled")

    # Auth middleware (for tokens) - only add if auth not disabled
    auth_token = None
    if not disable_auth:
        if auth_config is not None and hasattr(auth_config, "auth_token"):
            auth_token = auth_config.auth_token

        if auth_token:
            if logger.isEnabledFor(logging.INFO):
                logger.info("Auth token validation is enabled")
            app.add_middleware(
                AuthMiddleware, valid_token=auth_token, bypass_paths=["/docs"]
            )

    # Custom header middleware
    app.add_middleware(CustomHeaderMiddleware)

    # Loop prevention middleware (fast rejection path, minimal overhead)
    app.add_middleware(LoopPreventionMiddleware)

    # Response retry-after middleware
    app.add_middleware(RetryAfterMiddleware)

    # Security middleware to enforce state access through interfaces
    try:
        from src.core.app.middleware.security_middleware import add_security_middleware

        add_security_middleware(app)
        if logger.isEnabledFor(logging.INFO):
            logger.info("Security middleware is enabled")
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Failed to register SecurityMiddleware: %s", e, exc_info=True
            )

    # Domain exception mapping middleware (translate domain errors to HTTP)
    try:
        from src.core.app.middleware.exception_middleware import (
            DomainExceptionMiddleware,
        )

        app.add_middleware(DomainExceptionMiddleware)
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Failed to register DomainExceptionMiddleware: %s", e, exc_info=True
            )

    # Third-party exception handlers (connectivity, JSON decoding, validation)
    try:
        import httpx

        from src.core.app.exception_handlers import (
            httpx_request_error_handler,
            json_decode_error_handler,
            pydantic_validation_error_handler,
        )

        app.add_exception_handler(httpx.RequestError, httpx_request_error_handler)

        import json as _json

        from pydantic import ValidationError as _PydanticValidationError

        app.add_exception_handler(_json.JSONDecodeError, json_decode_error_handler)
        app.add_exception_handler(
            _PydanticValidationError, pydantic_validation_error_handler
        )
    except Exception as e:  # pragma: no cover - defensive
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Failed to register exception handlers: %s", e, exc_info=True
            )

    # Content rewriting middleware (if enabled)
    if config.rewriting.enabled:
        from src.core.app.middleware.content_rewriting_middleware import (
            ContentRewritingMiddleware,
        )
        from src.core.services.content_rewriter_service import ContentRewriterService

        rewriter = app.state.service_provider.get_required_service(
            ContentRewriterService
        )
        app.add_middleware(ContentRewritingMiddleware, rewriter=rewriter)
        if logger.isEnabledFor(logging.INFO):
            logger.info("Content rewriting middleware is enabled.")

    # LLM Assessment middleware (if enabled)
    if hasattr(config, "assessment") and getattr(config.assessment, "enabled", False):
        try:
            from src.core.app.middleware.assessment_middleware import (
                AssessmentMiddleware,
            )
            from src.core.services.assessment_service import AssessmentService

            assessment_service = app.state.service_provider.get_required_service(
                AssessmentService
            )
            app.add_middleware(
                AssessmentMiddleware, assessment_service=assessment_service  # type: ignore[arg-type]
            )
            if logger.isEnabledFor(logging.INFO):
                logger.info("LLM Assessment middleware is enabled")
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to register AssessmentMiddleware: %s", e, exc_info=True
                )

    # Request/response logging middleware (if enabled)
    request_logging = (
        config.logging.request_logging if hasattr(config, "logging") else False
    )
    response_logging = (
        config.logging.response_logging if hasattr(config, "logging") else False
    )

    if request_logging or response_logging:
        from src.core.app.middleware.logging_middleware import LoggingMiddleware

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Logging middleware is enabled",
                request_logging=request_logging,
                response_logging=response_logging,
            )
        app.add_middleware(
            LoggingMiddleware,
            log_requests=request_logging,
            log_responses=response_logging,
        )

    # SSO authentication middleware (if enabled)
    # Note: sso_enabled already checked above for legacy auth disabling
    if sso_enabled:
        try:
            from src.core.auth.sso.database import TokenRepository
            from src.core.auth.sso.middleware import AuthMiddleware as SSOAuthMiddleware
            from src.core.auth.sso.sandbox_handler import SandboxHandler
            from src.core.auth.sso.token_service import TokenService

            # Get SSO configuration
            sso_config = config.sso

            # Initialize SSO components
            token_service = TokenService.create_for_environment()
            token_repository = TokenRepository(sso_config.database_path)

            # Determine base URL for auth redirects
            if config.public_url:
                base_auth_url = f"{config.public_url.rstrip('/')}/auth/login"
            else:
                base_auth_url = f"http://{config.host}:{config.port}/auth/login"

            sandbox_handler = SandboxHandler(
                auth_url=base_auth_url,
                token_repository=token_repository,
            )

            # Create SSO auth middleware
            sso_auth_middleware = SSOAuthMiddleware(
                token_service=token_service,
                token_repository=token_repository,
                sandbox_handler=sandbox_handler,
            )

            # Add SSO middleware wrapper to FastAPI
            from src.core.app.middleware.sso_middleware_adapter import (
                SSOMiddlewareAdapter,
            )

            app.add_middleware(SSOMiddlewareAdapter, sso_middleware=sso_auth_middleware)

            if logger.isEnabledFor(logging.INFO):
                logger.info("SSO authentication middleware is enabled")
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to register SSO authentication middleware: %s",
                    e,
                    exc_info=True,
                )

    # Usage tracking middleware (if enabled)
    usage_tracking_enabled = (
        config.usage_tracking.enabled if hasattr(config, "usage_tracking") else False
    )

    if usage_tracking_enabled:
        try:
            from src.core.app.middleware.usage_tracking_middleware import (
                UsageTrackingMiddleware,
            )
            from src.core.interfaces.usage_recording_interface import (
                IUsageRecordingService,
            )

            usage_service = app.state.service_provider.get_required_service(
                IUsageRecordingService
            )
            app.add_middleware(
                UsageTrackingMiddleware, usage_recording_service=usage_service
            )
            if logger.isEnabledFor(logging.INFO):
                logger.info("Usage tracking middleware is enabled")
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to register UsageTrackingMiddleware: %s", e, exc_info=True
                )


def register_custom_middleware(app: FastAPI, *args: Any, **kwargs: Any) -> None:
    """Register custom middleware with the FastAPI application.

    Args:
        app: The FastAPI application
        *args: Positional arguments (middleware_class should be the first)
        **kwargs: Keyword arguments to pass to the middleware constructor
    """
    if not args:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning("No middleware class provided to register_custom_middleware")
        return

    middleware_class = args[0]
    try:
        app.add_middleware(middleware_class, **kwargs)
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                f"Successfully registered custom middleware: {middleware_class.__name__}"
            )
    except Exception as e:
        if logger.isEnabledFor(logging.ERROR):
            logger.error(
                f"Failed to register custom middleware: {middleware_class.__name__}",
                exc_info=e,
            )
