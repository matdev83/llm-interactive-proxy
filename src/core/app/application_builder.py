"""
Application builder using staged initialization pattern.

This module provides the ApplicationBuilder class that replaces the complex
monolithic ApplicationFactory with a clean, staged approach to application
initialization.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import Any

from fastapi import FastAPI

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.di_interface import IServiceProvider

from .stages.base import InitializationStage

logger = logging.getLogger(__name__)


class ApplicationBuilder:
    """
    Builder for creating FastAPI applications using staged initialization.

    This class replaces the complex ApplicationFactory with a clean, modular
    approach where initialization is broken down into discrete stages that
    can be executed in dependency order.

    Example:
        builder = (ApplicationBuilder()
                   .add_stage(CoreServicesStage())
                   .add_stage(BackendStage())
                   .add_stage(ProcessorStage()))
        app = await builder.build(config)
    """

    def __init__(self) -> None:
        """Initialize the application builder."""
        self._stages: dict[str, InitializationStage] = {}
        self._services = ServiceCollection()

    def add_stage(self, stage: InitializationStage) -> ApplicationBuilder:
        """
        Add an initialization stage to the builder.

        Args:
            stage: The initialization stage to add

        Returns:
            Self for method chaining

        Raises:
            ValueError: If a stage with the same name is already registered
        """
        if stage.name in self._stages:
            raise ValueError(f"Stage '{stage.name}' is already registered")

        self._stages[stage.name] = stage
        logger.debug(f"Added stage: {stage}")
        return self

    def add_default_stages(self) -> ApplicationBuilder:
        """
        Add the default stages needed for a production application.

        Returns:
            Self for method chaining
        """
        from .stages import (
            BackendStage,
            CommandStage,
            ControllerStage,
            CoreServicesStage,
            InfrastructureStage,
            ProcessorStage,
        )

        return (
            self.add_stage(CoreServicesStage())
            .add_stage(InfrastructureStage())
            .add_stage(BackendStage())
            .add_stage(CommandStage())
            .add_stage(ProcessorStage())
            .add_stage(ControllerStage())
        )

    # get_stages() removed: prefer observing via logs or extend builder for inspection

    def _get_execution_order(self) -> list[str]:
        """
        Calculate the execution order for stages using topological sort.

        This ensures that stages are executed in dependency order, with
        dependency stages running before dependent stages.

        Returns:
            List of stage names in execution order

        Raises:
            RuntimeError: If circular dependencies are detected
        """
        # Build dependency graph
        graph: dict[str, list[str]] = defaultdict(list)
        in_degree: dict[str, int] = defaultdict(int)

        # Initialize all nodes
        for stage_name in self._stages:
            in_degree[stage_name] = 0

        # Build graph edges
        for stage_name, stage in self._stages.items():
            for dep in stage.get_dependencies():
                if dep not in self._stages:
                    raise ValueError(
                        f"Stage '{stage_name}' depends on '{dep}' which is not registered"
                    )
                graph[dep].append(stage_name)
                in_degree[stage_name] += 1

        # Topological sort using Kahn's algorithm
        queue: deque[str] = deque(
            [name for name in self._stages if in_degree[name] == 0]
        )
        result: list[str] = []

        while queue:
            current: str = queue.popleft()
            result.append(current)

            # Remove edges from current node
            for neighbor in graph[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Check for cycles
        if len(result) != len(self._stages):
            remaining = set(self._stages.keys()) - set(result)
            raise RuntimeError(
                f"Circular dependency detected in stages. Remaining stages: {remaining}"
            )

        return result

    async def validate_stages(self, config: AppConfig) -> None:
        """
        Validate that all stages can be executed successfully.

        Args:
            config: The application configuration

        Raises:
            RuntimeError: If any stage validation fails
        """
        for stage_name, stage in self._stages.items():
            try:
                is_valid: bool = await stage.validate(self._services, config)
                if not is_valid:
                    raise RuntimeError(f"Stage '{stage_name}' validation failed")
            except Exception as e:  # type: ignore[misc]
                raise RuntimeError(f"Stage '{stage_name}' validation error: {e}") from e

    async def build(self, config: AppConfig) -> FastAPI:
        """
        Build the FastAPI application by executing all stages.

        Args:
            config: The application configuration

        Returns:
            Configured FastAPI application

        Raises:
            RuntimeError: If stage execution fails
        """
        logger.info("Starting application build process...")

        # Validate stages before execution
        await self.validate_stages(config)

        # Calculate execution order
        execution_order: list[str] = self._get_execution_order()
        logger.info(f"Executing stages in order: {execution_order}")

        # Execute stages in dependency order
        for stage_name in execution_order:
            stage: InitializationStage = self._stages[stage_name]
            logger.info(f"Executing stage: {stage_name}")

            try:
                await stage.execute(self._services, config)
                logger.debug(f"Stage '{stage_name}' completed successfully")
            except Exception as e:  # type: ignore[misc]
                logger.error(f"Stage '{stage_name}' failed: {e}")
                raise RuntimeError(f"Stage '{stage_name}' execution failed: {e}") from e

        # Build service provider
        service_provider: IServiceProvider = self._services.build_service_provider()
        logger.info("Service provider built successfully")

        # Create FastAPI application
        app: FastAPI = self._create_fastapi_app(config, service_provider)
        logger.info("FastAPI application created successfully")

        return app

    def build_compat(
        self, config: AppConfig, service_provider: IServiceProvider | None = None
    ) -> FastAPI:
        """
        Backward-compatible build method that accepts an optional service_provider.

        This method maintains compatibility with older tests that may pass a service_provider
        as a second argument. The service_provider is ignored in favor of the new staged
        initialization approach.

        Args:
            config: The application configuration
            service_provider: Optional service provider (ignored for compatibility)

        Returns:
            Configured FastAPI application
        """
        import asyncio

        try:
            asyncio.get_running_loop()
            # If we're in an async context, we need to run in a new thread
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future: concurrent.futures.Future[FastAPI] = executor.submit(
                    lambda: asyncio.run(self.build(config))
                )
                return future.result()
        except RuntimeError:
            # No running loop, we can use asyncio.run directly
            return asyncio.run(self.build(config))

    def _create_fastapi_app(
        self, config: AppConfig, service_provider: IServiceProvider
    ) -> FastAPI:
        """
        Create the FastAPI application with minimal setup.

        Args:
            config: The application configuration
            service_provider: The built service provider

        Returns:
            Configured FastAPI application
        """
        app: FastAPI = FastAPI(
            title="LLM Interactive Proxy",
            description="A proxy for interacting with LLM APIs",
            version="0.1.0",
        )

        # Store essential state
        app.state.service_provider = service_provider
        app.state.app_config = config

        # Ensure global DI accessor is in sync for legacy helpers/dependencies
        try:
            from src.core.di.services import set_service_provider

            set_service_provider(service_provider)
        except Exception:
            logger.debug("Unable to set global service provider", exc_info=True)

        # Configure middleware
        self._configure_middleware(app, config)

        # Install API key redaction filter into logging early in app lifecycle.
        try:
            from src.core.common.logging_utils import (
                discover_api_keys_from_config_and_env,
                install_api_key_redaction_filter,
            )

            # Use the discovery function to find all API keys from config and environment
            api_keys: list[str] = discover_api_keys_from_config_and_env(config)
            logger.debug(f"Discovered {len(api_keys)} API keys for redaction")

            install_api_key_redaction_filter(api_keys)
        except Exception:
            # Don't fail app creation if logging redaction cannot be installed
            logger.debug("Failed to install API key redaction filter", exc_info=True)

        # Register routes
        self._register_routes(app)

        # Register exception handlers
        self._register_exception_handlers(app)

        # Add lifecycle handlers
        self._add_lifecycle_handlers(app, service_provider)

        return app

    def _configure_middleware(self, app: FastAPI, config: AppConfig) -> None:
        """Configure middleware for the FastAPI application."""
        try:
            from src.core.app.middleware_config import configure_middleware

            configure_middleware(app, config)
        except ImportError:
            logger.warning("Middleware configuration not available")

    def _register_routes(self, app: FastAPI) -> None:
        """Register routes for the FastAPI application."""
        try:
            from src.core.app.controllers import register_routes

            register_routes(app)
        except ImportError:
            logger.warning("Route registration not available")

    def _register_exception_handlers(self, app: FastAPI) -> None:
        """Register exception handlers for the FastAPI application."""
        try:
            from src.core.transport.fastapi.exception_adapters import (
                register_exception_handlers,
            )

            register_exception_handlers(app)
        except ImportError:
            logger.warning("Exception handlers not available")

    def _add_lifecycle_handlers(
        self, app: FastAPI, service_provider: IServiceProvider
    ) -> None:
        """Add startup and shutdown handlers."""

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def,no-any-return,misc]
            # Startup
            logger.info("Application startup complete")
            yield
            # Shutdown
            logger.info("Shutting down application")
            # Clean up resources
            try:
                import httpx

                client: httpx.AsyncClient | None = service_provider.get_service(
                    httpx.AsyncClient
                )
                if client:
                    await client.aclose()
            except Exception:
                pass

        # Set lifespan handler
        app.router.lifespan_context = lifespan


# Convenience function for building applications
async def build_app_async(config: AppConfig | None = None) -> FastAPI:
    """
    Build a FastAPI application asynchronously using default stages.

    Args:
        config: Application configuration, defaults to loading from environment

    Returns:
        Configured FastAPI application
    """
    if config is None:
        config = AppConfig.from_env()

    builder: ApplicationBuilder = ApplicationBuilder().add_default_stages()
    return await builder.build(config)


def build_app(config: AppConfig | None = None) -> FastAPI:
    """
    Build a FastAPI application using default stages.

    This is a synchronous wrapper around build_app_async for compatibility
    with existing code that expects a synchronous build function.

    Args:
        config: Application configuration, defaults to loading from environment

    Returns:
        Configured FastAPI application
    """
    import asyncio

    if config is None:
        config = AppConfig.from_env()

    async def _build_wrapper() -> FastAPI:
        """Wrapper to defer coroutine creation until needed.

        Some tests may mock `build_app_async` with an AsyncMock whose return_value
        is itself a coroutine. In that case, awaiting once yields a coroutine
        object. Detect and await again to produce the FastAPI app.
        """
        res: FastAPI | Any = await build_app_async(config)
        import asyncio as _asyncio

        if _asyncio.iscoroutine(res):
            final_result: FastAPI = await res  # type: ignore[misc]
            return final_result
        final_result = res  # type: ignore[assignment]
        return final_result

    try:
        asyncio.get_running_loop()
        # If we're in an async context, we need to run in a new thread
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future: concurrent.futures.Future[FastAPI] = executor.submit(
                lambda: asyncio.run(_build_wrapper())
            )
            return future.result()
    except RuntimeError:
        # No running loop, we can use asyncio.run directly
        return asyncio.run(_build_wrapper())
