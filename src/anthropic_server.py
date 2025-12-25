from __future__ import annotations

import asyncio
import logging

import uvicorn
from fastapi import FastAPI

from src.core.app.application_builder import build_app_async
from src.core.app.controllers import _register_anthropic_endpoints
from src.core.config.app_config import AppConfig

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def create_anthropic_app_async(
    config: AppConfig, built_app: FastAPI | None = None
) -> FastAPI:
    """
    Create a lightweight FastAPI application with only Anthropic routes (async).

    Args:
        config: Application configuration
        built_app: Optional existing main application. If provided, service provider
                  will be extracted from it to avoid double initialization.
    """
    if built_app:
        service_provider = getattr(built_app.state, "service_provider", None)
        app_config = config
    else:
        built_app_internal = await build_app_async(config)
        service_provider = getattr(built_app_internal.state, "service_provider", None)
        app_config = config

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

    # Register Codebuff WebSocket endpoint if enabled
    if app_config.codebuff.enabled:
        if logger.isEnabledFor(logging.INFO):
            logger.info("Codebuff WebSocket server is enabled, registering endpoint")
        try:
            from src.codebuff.factory import create_codebuff_server

            codebuff_server = create_codebuff_server(app_config, service_provider)
            codebuff_server.register_endpoint(app)
            app.state.codebuff_server = codebuff_server
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    f"Codebuff WebSocket endpoint registered at {app_config.codebuff.websocket_path}"
                )
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Failed to register Codebuff WebSocket endpoint: {e}",
                    exc_info=True,
                )
    else:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Codebuff WebSocket server is disabled")

    return app


def create_anthropic_app(config: AppConfig) -> FastAPI:
    """
    Create a lightweight FastAPI application with only Anthropic routes (sync wrapper).
    """
    try:
        # Check if we're already in an async context
        asyncio.get_running_loop()
        # If we're in an async context, use a thread pool to run the async function
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future: concurrent.futures.Future[FastAPI] = executor.submit(
                lambda: asyncio.run(create_anthropic_app_async(config))
            )
            return future.result()
    except RuntimeError:
        # No running loop, we can use asyncio.run directly
        return asyncio.run(create_anthropic_app_async(config))


async def main() -> None:
    """
    Main entry point for the Anthropic server.
    """
    # Load configuration with CLI argument support
    from src.core.config.cli_args import get_config_with_cli_args

    env_with_cli = get_config_with_cli_args()
    config = AppConfig.from_env(environ=env_with_cli)

    app = await create_anthropic_app_async(config)

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
