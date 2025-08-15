from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware

from src.core.common.logging import LoggingMiddleware, get_logger
from src.core.di.services import get_service_provider
from src.core.security import APIKeyMiddleware, AuthMiddleware
from src.request_middleware import CustomHeaderMiddleware
from src.response_middleware import RetryAfterMiddleware

logger = get_logger(__name__)


def configure_middleware(app: FastAPI, config: dict[str, Any]) -> None:
    """Configure middleware for the application.

    Args:
        app: The FastAPI application
        config: The application configuration
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
    if not config.get("disable_auth", False):
        api_keys = config.get("api_keys", [])
        logger.info("API Key authentication is enabled", key_count=len(api_keys))
        app.add_middleware(APIKeyMiddleware, valid_keys=api_keys)
    else:
        logger.info("API Key authentication is disabled")

    # Auth middleware (for tokens)
    auth_token = config.get("auth_token")
    if auth_token:
        logger.info("Auth token validation is enabled")
        app.add_middleware(
            AuthMiddleware, valid_token=auth_token, bypass_paths=["/docs"]
        )

    # Custom header middleware
    app.add_middleware(CustomHeaderMiddleware)

    # Response retry-after middleware
    app.add_middleware(RetryAfterMiddleware)

    # Request/response logging middleware (if enabled)
    request_logging = config.get("request_logging", False)
    response_logging = config.get("response_logging", False)

    if request_logging or response_logging:
        logger.info(
            "Logging middleware is enabled",
            request_logging=request_logging,
            response_logging=response_logging,
        )
        provider = get_service_provider()
        logging_middleware = provider.get_required_service(LoggingMiddleware)
        app.add_middleware(
            logging_middleware,
            request_logging=request_logging,
            response_logging=response_logging,
        )


def register_custom_middleware(
    app: FastAPI, middleware_class: type[BaseHTTPMiddleware], **kwargs: Any
) -> None:
    """Register custom middleware with the FastAPI application.

    Args:
        app: The FastAPI application
        middleware_class: The middleware class to register
        **kwargs: Keyword arguments to pass to the middleware constructor
    """
    app.add_middleware(middleware_class, **kwargs)
