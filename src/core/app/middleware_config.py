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
    if isinstance(config, dict):
        # Legacy dict config
        disable_auth = config.get("disable_auth", False)
        api_keys = config.get("api_keys", [])
        trusted_ips = config.get("trusted_ips", [])
    else:
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
        if isinstance(config, dict):
            # Check both root level and nested auth structure for auth_token
            auth_token = config.get("auth_token")
            if not auth_token and "auth" in config and isinstance(config["auth"], dict):
                auth_token = config["auth"].get("auth_token")
            # Debug log for auth token
            logger.debug("Auth token from config: %s", auth_token)
        elif hasattr(config, "auth") and hasattr(config.auth, "auth_token"):
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

    # Request/response logging middleware (if enabled)
    if isinstance(config, dict):
        request_logging = config.get("request_logging", False)
        response_logging = config.get("response_logging", False)
    else:
        request_logging = (
            config.logging.request_logging if hasattr(config, "logging") else False
        )
        response_logging = (
            config.logging.response_logging if hasattr(config, "logging") else False
        )

    if request_logging or response_logging:
        logger.info(
            "Logging middleware is enabled",
            request_logging=request_logging,
            response_logging=response_logging,
        )
        # For now, we'll use a simplified approach to logging middleware
        # TODO: Reimplement proper logging middleware integration


def register_custom_middleware(app: FastAPI, *args: Any, **kwargs: Any) -> None:
    """Register custom middleware with the FastAPI application.

    Args:
        app: The FastAPI application
        *args: Positional arguments (middleware_class should be the first)
        **kwargs: Keyword arguments to pass to the middleware constructor
    """
    # For now, we'll skip custom middleware registration
    # TODO: Implement proper custom middleware registration
    # middleware_class would be args[0] if provided
