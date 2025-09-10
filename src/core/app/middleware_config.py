from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from src.core.common.logging import get_logger
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

    # API key authentication middleware (if enabled)
    # New AppConfig object
    disable_auth = config.auth.disable_auth if hasattr(config, "auth") else False
    api_keys = config.auth.api_keys if hasattr(config, "auth") else []
    trusted_ips = config.auth.trusted_ips if hasattr(config, "auth") else []

    # Respect environment override for disabling auth (useful for tests)
    env_disable = os.getenv("DISABLE_AUTH", "").lower() == "true"
    disable_auth = disable_auth or env_disable

    if not disable_auth:
        # If running under pytest and no keys provided, add a default test key to ease integration tests
        if not api_keys and os.environ.get("PYTEST_CURRENT_TEST"):
            api_keys = ["test-proxy-key"]
        logger.info("API Key authentication is enabled", key_count=len(api_keys))
        # Add API Key middleware
        app.add_middleware(
            APIKeyMiddleware, valid_keys=api_keys, trusted_ips=trusted_ips
        )
    else:
        logger.info("API Key authentication is disabled")

    # Auth middleware (for tokens) - only add if auth not disabled
    auth_token = None
    if not disable_auth:
        if hasattr(config, "auth") and hasattr(config.auth, "auth_token"):
            auth_token = config.auth.auth_token

        if auth_token:
            logger.info("Auth token validation is enabled")
            app.add_middleware(
                AuthMiddleware, valid_token=auth_token, bypass_paths=["/docs"]
            )

    # Custom header middleware
    app.add_middleware(CustomHeaderMiddleware)

    # Response retry-after middleware
    app.add_middleware(RetryAfterMiddleware)

    # Security middleware to enforce state access through interfaces
    try:
        from src.core.app.middleware.security_middleware import add_security_middleware

        add_security_middleware(app)
        logger.info("Security middleware is enabled")
    except Exception as e:
        logger.warning("Failed to register SecurityMiddleware: %s", e, exc_info=True)

    # Domain exception mapping middleware (translate domain errors to HTTP)
    try:
        from src.core.app.middleware.exception_middleware import (
            DomainExceptionMiddleware,
        )

        app.add_middleware(DomainExceptionMiddleware)
    except Exception as e:
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
        logger.warning("Failed to register exception handlers: %s", e, exc_info=True)

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
        logger.info("Content rewriting middleware is enabled.")

    # Request/response logging middleware (if enabled)
    request_logging = (
        config.logging.request_logging if hasattr(config, "logging") else False
    )
    response_logging = (
        config.logging.response_logging if hasattr(config, "logging") else False
    )

    if request_logging or response_logging:
        from src.core.app.middleware.logging_middleware import LoggingMiddleware

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


def register_custom_middleware(app: FastAPI, *args: Any, **kwargs: Any) -> None:
    """Register custom middleware with the FastAPI application.

    Args:
        app: The FastAPI application
        *args: Positional arguments (middleware_class should be the first)
        **kwargs: Keyword arguments to pass to the middleware constructor
    """
    if not args:
        logger.warning("No middleware class provided to register_custom_middleware")
        return

    middleware_class = args[0]
    try:
        app.add_middleware(middleware_class, **kwargs)
        logger.info(
            f"Successfully registered custom middleware: {middleware_class.__name__}"
        )
    except Exception as e:
        logger.error(
            f"Failed to register custom middleware: {middleware_class.__name__}",
            exc_info=e,
        )
