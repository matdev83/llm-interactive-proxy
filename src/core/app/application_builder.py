"""
Application builder using staged initialization pattern.

This module provides the ApplicationBuilder class that replaces the complex
monolithic ApplicationFactory with a clean, staged approach to application
initialization.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict, deque
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

from src.core.di.container import ServiceCollection
from src.core.di.services import get_service_collection
from src.core.interfaces.di_interface import IServiceProvider

from .stages.base import InitializationStage

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.core.config.app_config import AppConfig


def _register_sandboxing_handler(
    config: AppConfig, service_provider: IServiceProvider
) -> None:
    """Register file sandboxing handler if enabled.

    Note: File sandboxing is now handled by the UnifiedToolSecurityHandler
    which is registered via the security registrar (src/core/di/registrations/security.py).
    Handler registration with ToolCallReactorService happens post-build via provider lifecycle hooks.

    This function is kept for backward compatibility but no longer performs registration.
    Security services are registered via the security registrar during DI setup.

    Args:
        config: Application configuration
        service_provider: Service provider for resolving dependencies
    """
    sandboxing_cfg = getattr(config, "sandboxing", None)
    if sandboxing_cfg is None or not getattr(sandboxing_cfg, "enabled", False):
        if logger.isEnabledFor(logging.INFO):
            logger.info("File access sandboxing: DISABLED")
        return

    try:
        errors = sandboxing_cfg.validate_configuration()
    except Exception as exc:
        if logger.isEnabledFor(logging.ERROR):
            logger.error(
                "File access sandboxing configuration is invalid: %s",
                exc,
                exc_info=True,
            )
            logger.error("Sandboxing will be disabled")
        return

    if errors:
        if logger.isEnabledFor(logging.ERROR):
            logger.error(
                "File access sandboxing configuration is invalid: %s",
                "; ".join(str(e) for e in errors),
            )
            logger.error("Sandboxing will be disabled")
        return

    session_cfg = getattr(config, "session", None)
    project_dir_resolution_mode = getattr(
        session_cfg, "project_dir_resolution_mode", "auto"
    )
    if str(project_dir_resolution_mode).lower() == "disabled":
        if logger.isEnabledFor(logging.INFO):
            logger.info("project directory resolution is DISABLED")
            logger.info("File access sandboxing status: DISABLED (dependency not met)")
        return

    if logger.isEnabledFor(logging.INFO):
        logger.info("File access sandboxing: ENABLED (via UnifiedToolSecurityHandler)")


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

        # Start from the globally configured service collection so that any
        # pre-registered overrides (for example in tests) are honoured. Create a
        # fresh ServiceCollection instance to avoid mutating the global
        # container while still inheriting its registrations.
        base_collection = get_service_collection()
        self._services = ServiceCollection()
        try:
            self._services._descriptors.update(base_collection._descriptors)
        except AttributeError:
            # Fallback for unexpected implementations of ServiceCollection
            for service_type, descriptor in getattr(
                base_collection, "_descriptors", {}
            ).items():
                self._services._descriptors[service_type] = descriptor

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
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Added stage: %s", stage)
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
            SteeringStage,
        )

        return (
            self.add_stage(InfrastructureStage())
            .add_stage(CoreServicesStage())
            .add_stage(
                SteeringStage()
            )  # After core services, before backends to ensure handlers are available
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
        if logger.isEnabledFor(logging.INFO):
            logger.info("Starting application build process...")

        # Validate stages before execution
        await self.validate_stages(config)

        # Calculate execution order
        execution_order: list[str] = self._get_execution_order()
        if logger.isEnabledFor(logging.INFO):
            logger.info("Executing stages in order: %s", execution_order)

        # Execute stages in dependency order
        for stage_name in execution_order:
            stage: InitializationStage = self._stages[stage_name]
            if logger.isEnabledFor(logging.INFO):
                logger.info("Executing stage: %s", stage_name)

            try:
                await stage.execute(self._services, config)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Stage '%s' completed successfully", stage_name)
            except Exception as e:  # type: ignore[misc]
                logger.error(f"Stage '{stage_name}' failed: {e}")
                # Ensure ServiceCollection cleanup tasks are awaited on failure
                with contextlib.suppress(Exception):
                    await self._services.dispose()
                raise RuntimeError(f"Stage '{stage_name}' execution failed: {e}") from e

        # Build service provider
        service_provider: IServiceProvider = self._services.build_service_provider()
        if logger.isEnabledFor(logging.INFO):
            logger.info("Service provider built successfully")

        # Create FastAPI application
        app: FastAPI = self._create_fastapi_app(config, service_provider)
        if logger.isEnabledFor(logging.INFO):
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

        # Bridge application state service methods onto FastAPI state for compatibility
        try:
            from src.core.interfaces.application_state_interface import (
                IApplicationState,
            )

            app_state_service: IApplicationState = (
                service_provider.get_required_service(IApplicationState)  # type: ignore[type-abstract]
            )

            try:
                app.state.application_state_service = app_state_service
            except (AttributeError, TypeError) as err:
                # AttributeError: app.state is read-only or missing
                # TypeError: type mismatch or assignment not supported
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to expose application_state_service on app.state: %s",
                        type(err).__name__,
                        exc_info=True,
                    )

            if hasattr(app_state_service, "set_state_provider"):
                try:
                    app_state_service.set_state_provider(app.state)  # type: ignore[attr-defined]
                except (AttributeError, TypeError, RuntimeError) as err:
                    # AttributeError: method missing or wrong signature
                    # TypeError: type mismatch in arguments
                    # RuntimeError: state corruption or threading issues
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Failed to set state provider on application state service: %s",
                            type(err).__name__,
                            exc_info=True,
                        )
            for attribute_name in dir(app_state_service):
                if attribute_name.startswith("_"):
                    continue
                if hasattr(app.state, attribute_name):
                    continue
                attribute_value = getattr(app_state_service, attribute_name)
                if callable(attribute_value):
                    try:
                        setattr(app.state, attribute_name, attribute_value)
                    except (AttributeError, TypeError) as err:
                        # AttributeError: app.state attribute is read-only or missing
                        # TypeError: type mismatch or assignment not supported
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Failed to expose application state attribute '%s' on app.state: %s",
                                attribute_name,
                                type(err).__name__,
                                exc_info=True,
                            )
        except (AttributeError, TypeError, RuntimeError) as err:
            # AttributeError: app.state or app_state_service missing expected attributes
            # TypeError: type mismatches during attribute access/setting
            # RuntimeError: state corruption or threading issues
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Unable to bind application state service methods to FastAPI state: %s",
                    type(err).__name__,
                    exc_info=True,
                )

        # Ensure global DI accessor is in sync for legacy helpers/dependencies
        try:
            from src.core.di.services import set_service_provider

            set_service_provider(service_provider)
        except (ImportError, AttributeError, RuntimeError) as err:
            # ImportError: module not available
            # AttributeError: function missing or wrong signature
            # RuntimeError: threading or state corruption issues
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Unable to set global service provider: %s",
                    type(err).__name__,
                    exc_info=True,
                )

        # Configure middleware
        self._configure_middleware(app, config)

        # Install API key redaaction filter into logging early in app lifecycle.
        try:
            from src.core.common.logging_utils import (
                discover_api_keys_from_config_and_env,
                install_api_key_redaction_filter,
            )

            # Discover API keys from all sources for redaction
            api_keys = discover_api_keys_from_config_and_env(config)
            install_api_key_redaction_filter(api_keys)
            if logger.isEnabledFor(logging.INFO):
                logger.info("API key redaction filter installed.")
        except (ImportError, AttributeError, ValueError, RuntimeError) as err:
            # ImportError: logging_utils module not available
            # AttributeError: functions missing or wrong signature
            # ValueError: invalid API key format or config
            # RuntimeError: logging system initialization issues
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to install API key redaction filter: %s",
                    type(err).__name__,
                    exc_info=True,
                )

        # Register routes
        self._register_routes(app)

        # Security services (including sandboxing) are now registered via
        # the security registrar during DI setup. Handler registration with
        # ToolCallReactorService happens post-build via provider lifecycle hooks.
        # This call is kept for backward compatibility but does nothing.
        _register_sandboxing_handler(config, service_provider)

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
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Middleware configuration not available")

    def _register_routes(self, app: FastAPI) -> None:
        """Register routes for the FastAPI application."""
        try:
            from src.core.app.controllers import register_routes

            register_routes(app)
        except ImportError:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Route registration not available")

    def _register_exception_handlers(self, app: FastAPI) -> None:
        """Register exception handlers for the FastAPI application."""
        try:
            from src.core.transport.fastapi.exception_adapters import (
                register_exception_handlers,
            )

            register_exception_handlers(app)
        except ImportError:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Exception handlers not available")

    def _add_lifecycle_handlers(
        self, app: FastAPI, service_provider: IServiceProvider
    ) -> None:
        """Add startup and shutdown handlers."""

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def,no-any-return,misc]
            # Startup
            if logger.isEnabledFor(logging.INFO):
                logger.info("Application startup complete")
            yield
            # Shutdown
            if logger.isEnabledFor(logging.INFO):
                logger.info("Shutting down application")

            # Shutdown backends to prevent resource leaks (processes, connections)
            try:
                from src.core.interfaces.backend_lifecycle_manager_interface import (
                    IBackendLifecycleManager,
                )

                backend_lifecycle_manager = service_provider.get_service(
                    IBackendLifecycleManager  # type: ignore[type-abstract]
                )
                if backend_lifecycle_manager:
                    await backend_lifecycle_manager.shutdown_all()
            except (RuntimeError, AttributeError, asyncio.CancelledError) as exc:
                # Best-effort shutdown - log specific shutdown errors
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to shut down backends: %s",
                        type(exc).__name__,
                        exc_info=True,
                    )
            except Exception:
                # Best-effort shutdown - catch-all for other errors
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning("Failed to shut down backends", exc_info=True)

            # Dispose of ServiceCollection to await pending cleanup tasks

            # This ensures cleanup tasks created when replacing httpx.AsyncClient
            # instances are properly awaited before closing the final client
            try:
                await self._services.dispose()
            except (RuntimeError, AttributeError, asyncio.CancelledError) as exc:
                # Best-effort disposal - log specific disposal errors
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to dispose ServiceCollection: %s",
                        type(exc).__name__,
                        exc_info=True,
                    )
            except Exception:
                # Best-effort disposal; ignore errors to avoid masking real failures
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning("Failed to dispose ServiceCollection", exc_info=True)
            # Clean up resources
            try:
                import httpx

                client: httpx.AsyncClient | None = service_provider.get_service(
                    httpx.AsyncClient
                )
                if client:
                    await client.aclose()
            except (RuntimeError, AttributeError):
                # Ignore errors when closing client
                pass

            # Attempt to gracefully stop background services (e.g., wire capture)
            try:
                from src.core.interfaces.wire_capture_interface import IWireCapture

                wire_capture = service_provider.get_service(IWireCapture)  # type: ignore[type-abstract]
                if wire_capture and hasattr(wire_capture, "shutdown"):
                    if logger.isEnabledFor(logging.INFO):
                        logger.info("Shutting down wire capture service...")
                    # type: ignore[attr-defined]
                    await wire_capture.shutdown()  # pyright: ignore[reportAttributeAccessIssue]
                    if logger.isEnabledFor(logging.INFO):
                        logger.info("Wire capture service shut down successfully.")
            except (RuntimeError, AttributeError, asyncio.CancelledError) as exc:
                # Best-effort shutdown - log specific shutdown errors
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to shut down wire capture service: %s",
                        type(exc).__name__,
                        exc_info=True,
                    )
            except Exception:
                # Best-effort shutdown; ignore errors to avoid masking real failures
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Failed to shut down wire capture service", exc_info=True
                    )

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
        from src.core.config.app_config import AppConfig

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
        from src.core.config.app_config import AppConfig

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
