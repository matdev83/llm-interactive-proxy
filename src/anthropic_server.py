from __future__ import annotations

import asyncio
import logging

import uvicorn
from fastapi import FastAPI

from src.core.app.application_factory import build_app_with_config
from src.core.app.controllers import _register_anthropic_endpoints
from src.core.config.app_config import AppConfig

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_anthropic_app(config: AppConfig) -> FastAPI:
    """
    Create a lightweight FastAPI application with only Anthropic routes.
    """
    built_app, app_config = build_app_with_config(config)

    service_provider = getattr(built_app.state, "service_provider", None)
    if service_provider is None and logger.isEnabledFor(logging.WARNING):
        logger.warning(
            "Service provider missing on base application; Anthropic routes may fail."
        )

    app = FastAPI(
        title="Anthropic LLM Interactive Proxy",
        description="A proxy for interacting with Anthropic LLM APIs",
        version="0.1.0",
        lifespan=None,
    )

    if service_provider is not None:
        app.state.service_provider = service_provider

    _register_anthropic_endpoints(app, prefix="")
    app.state.app_config = app_config
    return app


async def main() -> None:
    """
    Main entry point for the Anthropic server.
    """
    config = AppConfig.from_env()

    app = create_anthropic_app(config)

    if config.anthropic_port is None:
        raise ValueError("Anthropic port must be set to run the Anthropic server.")

    server_config = uvicorn.Config(
        app,
        host=config.host,
        port=config.anthropic_port,
        log_level=config.logging.level.value.lower(),
    )
    server = uvicorn.Server(server_config)

    if logger.isEnabledFor(logging.INFO):
        logger.info(
            f"Starting Anthropic server on http://{config.host}:{config.anthropic_port}"
        )
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
