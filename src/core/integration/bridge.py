"""
Integration Bridge

Manages the coexistence of old and new architectures during the migration.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI

# No longer using adapters - direct service usage
from src.core.di.services import get_service_collection, set_service_provider
from src.core.interfaces.di import IServiceProvider
from src.core.interfaces.session_service import ISessionService
from src.core.services.session_migration_service import SessionMigrationService

logger = logging.getLogger(__name__)


class IntegrationBridge:
    """Manages the integration between old and new architectures."""

    def __init__(self, app: FastAPI):
        """Initialize the integration bridge.

        Args:
            app: The FastAPI application
        """
        self.app = app
        self.feature_flags = self._load_feature_flags()
        self.legacy_initialized = False
        self.new_initialized = False

    def _load_feature_flags(self) -> dict[str, bool]:
        """Load feature flags from environment variables.

        Returns:
            Dictionary of feature flags with all new services enabled by default
        """
        return {
            "use_new_session_service": True,
            "use_new_command_service": True,
            "use_new_backend_service": True,
            "use_new_request_processor": True,
            "enable_dual_mode": True,
        }

    def _get_bool_env(self, key: str, default: bool) -> bool:
        """Get a boolean environment variable.

        Args:
            key: Environment variable key
            default: Default value

        Returns:
            Boolean value
        """
        value = os.environ.get(key, "").lower()
        if value in ("true", "1", "yes", "on"):
            return True
        elif value in ("false", "0", "no", "off"):
            return False
        return default

        # Legacy initialization methods have been removed

        # Import legacy backend classes
        from src.connectors.anthropic import AnthropicBackend
        from src.connectors.gemini import GeminiBackend
        from src.connectors.openai import OpenAIConnector
        from src.connectors.openrouter import OpenRouterBackend
        from src.connectors.qwen_oauth import QwenOAuthConnector
        from src.connectors.zai import ZAIConnector

        # Get HTTP client. Create a real httpx.AsyncClient so pytest-httpx
        # can intercept requests during tests. Avoid special no-network
        # clients which prevent pytest-httpx from consuming mocked responses.
        client_httpx = getattr(self.app.state, "httpx_client", None)
        if client_httpx is None:
            import httpx

            timeout = getattr(self.app.state, "config", {}).get("proxy_timeout", 300)
            client_httpx = httpx.AsyncClient(timeout=timeout)
            self.app.state.httpx_client = client_httpx

        # Initialize backends
        openai_backend = OpenAIConnector(client_httpx)
        openrouter_backend = OpenRouterBackend(client_httpx)
        gemini_backend = GeminiBackend(client_httpx)
        anthropic_backend = AnthropicBackend(client_httpx)
        qwen_oauth_backend = QwenOAuthConnector(client_httpx)
        zai_backend = ZAIConnector(client_httpx)

        # Set up API keys
        openrouter_keys = self.config.get("openrouter_api_keys", {})
        if openrouter_keys:
            openrouter_backend.api_keys = list(openrouter_keys.values())

        gemini_keys = self.config.get("gemini_api_keys", {})
        if gemini_keys:
            gemini_backend.api_keys = list(gemini_keys.values())
        else:
            # Add a test key for compatibility
            gemini_backend.api_keys = ["local-cli"]

        openai_keys = self.config.get("openai_api_keys", {})
        if openai_keys:
            openai_backend.api_keys = list(openai_keys.values())

        # Store backends on app state for legacy compatibility
        self.app.state.openai_backend = openai_backend
        self.app.state.openrouter_backend = openrouter_backend
        self.app.state.gemini_backend = gemini_backend
        self.app.state.anthropic_backend = anthropic_backend
        self.app.state.qwen_oauth_backend = qwen_oauth_backend
        self.app.state.zai_backend = zai_backend

        # Set up other legacy app state attributes
        if not hasattr(self.app.state, "command_prefix"):
            self.app.state.command_prefix = self.config.get("command_prefix", "!/")

        if not hasattr(self.app.state, "project_metadata"):
            from src.core.metadata import _load_project_metadata

            project_name, project_version = _load_project_metadata()
            self.app.state.project_metadata = {
                "name": project_name,
                "version": project_version,
            }

        # Set up session manager if not present
        if not hasattr(self.app.state, "session_manager"):
            from src.session import SessionManager

            default_mode = self.config.get("interactive_mode", True)
            failover_routes = getattr(self.app.state, "failover_routes", {})
            self.app.state.session_manager = SessionManager(
                default_interactive_mode=default_mode, failover_routes=failover_routes
            )

        logger.debug("Legacy backends initialized synchronously on app state")

    async def _setup_legacy_backends(self) -> None:
        """Set up legacy backend objects on app state for backward compatibility."""
        if not hasattr(self.app.state, "config"):
            logger.warning(
                "No config found on app state, skipping legacy backend setup"
            )
            return

        config = self.app.state.config

        # Import legacy backend classes
        from src.connectors.anthropic import AnthropicBackend
        from src.connectors.gemini import GeminiBackend
        from src.connectors.openai import OpenAIConnector
        from src.connectors.openrouter import OpenRouterBackend
        from src.connectors.qwen_oauth import QwenOAuthConnector
        from src.connectors.zai import ZAIConnector

        # Get HTTP client; prefer an existing client on app.state, otherwise
        # create an AsyncClient. pytest-httpx will intercept this client in
        # tests so mocked responses are consumed as expected.
        client_httpx = getattr(self.app.state, "httpx_client", None)
        if client_httpx is None:
            import httpx

            client_httpx = httpx.AsyncClient(timeout=config.get("proxy_timeout", 300))
            self.app.state.httpx_client = client_httpx

        # Initialize backends
        openai_backend = OpenAIConnector(client_httpx)
        openrouter_backend = OpenRouterBackend(client_httpx)
        gemini_backend = GeminiBackend(client_httpx)
        anthropic_backend = AnthropicBackend(client_httpx)
        qwen_oauth_backend = QwenOAuthConnector(client_httpx)
        zai_backend = ZAIConnector(client_httpx)

        # Set up API keys
        openrouter_keys = config.get("openrouter_api_keys", {})
        if openrouter_keys:
            openrouter_backend.api_keys = list(openrouter_keys.values())

        gemini_keys = config.get("gemini_api_keys", {})
        if gemini_keys:
            gemini_backend.api_keys = list(gemini_keys.values())
        else:
            # Add a test key for compatibility
            gemini_backend.api_keys = ["local-cli"]

        openai_keys = config.get("openai_api_keys", {})
        if openai_keys:
            openai_backend.api_keys = list(openai_keys.values())

        # Store backends on app state for legacy compatibility
        self.app.state.openai_backend = openai_backend
        self.app.state.openrouter_backend = openrouter_backend
        self.app.state.gemini_backend = gemini_backend
        self.app.state.anthropic_backend = anthropic_backend
        self.app.state.qwen_oauth_backend = qwen_oauth_backend
        self.app.state.zai_backend = zai_backend

        # Set up other legacy app state attributes
        if not hasattr(self.app.state, "command_prefix"):
            self.app.state.command_prefix = config.get("command_prefix", "!/")

        if not hasattr(self.app.state, "project_metadata"):
            from src.core.metadata import _load_project_metadata

            project_name, project_version = _load_project_metadata()
            self.app.state.project_metadata = {
                "name": project_name,
                "version": project_version,
            }

        # Set up session manager if not present
        if not hasattr(self.app.state, "session_manager"):
            from src.session import SessionManager

            default_mode = config.get("interactive_mode", True)
            failover_routes = getattr(self.app.state, "failover_routes", {})
            self.app.state.session_manager = SessionManager(
                default_interactive_mode=default_mode, failover_routes=failover_routes
            )

        logger.debug("Legacy backends initialized on app state")

    async def initialize_new_architecture(self) -> None:
        """Initialize the new SOLID architecture."""
        if self.new_initialized:
            return

        logger.info("Initializing new SOLID architecture")

        # Get service collection
        services = get_service_collection()

        # Register adapters that bridge legacy and new systems
        self._register_bridge_services(services)

        # Build and set service provider
        provider = services.build_service_provider()
        set_service_provider(provider)

        # Store provider in app state
        self.app.state.service_provider = provider

        self.new_initialized = True
        logger.info("New SOLID architecture initialized")

    async def initialize(self) -> None:
        """Initialize both legacy and new architectures."""
        try:
            await self.initialize_legacy_architecture()
        except ImportError as e:
            logger.info(f"Skipping legacy architecture initialization: {e}")
        await self.initialize_new_architecture()

    def _register_bridge_services(self, services) -> None:
        """Register services for the new architecture.

        Args:
            services: The service collection
        """
        # We no longer use adapters - the new architecture is fully independent
        # and the integration bridge only handles session synchronization

        # No need to register adapters anymore - the application_factory.py
        # handles registration of all required services
        from src.core.app.application_factory import register_services

        register_services(services, self.app)

        logger.info("Using new architecture services directly (no adapters)")

        # Note: The application_factory.py now registers:
        # - BackendService for IBackendService
        # - CommandService for ICommandService
        # - AppConfig for IConfig

    def get_service_provider(self) -> IServiceProvider | None:
        """Get the service provider if new architecture is initialized.

        Returns:
            Service provider or None
        """
        if self.new_initialized:
            return getattr(self.app.state, "service_provider", None)
        return None

    def should_use_new_service(self, service_name: str) -> bool:
        """Check if we should use the new implementation of a service.

        Args:
            service_name: Name of the service

        Returns:
            True if new service should be used
        """
        flag_key = f"use_new_{service_name}"
        return self.feature_flags.get(flag_key, False)

    def is_dual_mode_enabled(self) -> bool:
        """Check if dual mode is enabled.

        Returns:
            True if dual mode is enabled
        """
        return self.feature_flags.get("enable_dual_mode", True)

    async def sync_session(self, session_id: str) -> None:
        """Synchronize session between old and new architectures.

        Args:
            session_id: The ID of the session to synchronize
        """
        if not (self.legacy_initialized and self.new_initialized):
            logger.warning(
                "Cannot sync session: both architectures must be initialized"
            )
            return

        try:
            # Get service provider
            provider = self.get_service_provider()
            if not provider:
                logger.warning("Cannot sync session: service provider not available")
                return

            # Get session migration service
            migration_service = provider.get_service(SessionMigrationService)
            if not migration_service:
                logger.warning("Cannot sync session: migration service not available")
                return

            # Get session services
            new_session_service = provider.get_service(ISessionService)  # type: ignore
            if not new_session_service:
                logger.warning("Cannot sync session: new session service not available")
                return

            # Get legacy session
            if not hasattr(self.app.state, "session_manager"):
                logger.warning("Cannot sync session: session manager not available")
                return

            session_manager = self.app.state.session_manager
            legacy_session = session_manager.get_session(session_id)
            if not legacy_session:
                logger.warning(
                    f"Cannot sync session: legacy session {session_id} not found"
                )
                return

            # Get new session
            _ = await new_session_service.get_session(session_id)

            # Sync from legacy to new
            migrated_session = await migration_service.migrate_legacy_session(
                legacy_session
            )
            await new_session_service.update_session(migrated_session)

            # Sync from new to legacy
            await migration_service.sync_session_state(legacy_session, migrated_session)

            logger.debug(
                f"Successfully synchronized session {session_id} between architectures"
            )

        except Exception as e:
            logger.error(f"Failed to sync session {session_id}: {e}", exc_info=True)

    def ensure_legacy_state(self) -> None:
        """Ensure legacy state is initialized. Use this for lazy initialization in tests."""
        if not self.legacy_initialized:
            self._setup_legacy_backends_sync()
            self.legacy_initialized = True

    async def cleanup(self) -> None:
        """Cleanup both architectures."""
        logger.info("Cleaning up integration bridge")

        # Cleanup will be handled by individual lifespan managers

        self.legacy_initialized = False
        self.new_initialized = False


# Global bridge instance
_bridge: IntegrationBridge | None = None


def get_integration_bridge(app: FastAPI | None = None) -> IntegrationBridge:
    """Get the global integration bridge.

    Args:
        app: FastAPI application (required for first call)

    Returns:
        The integration bridge
    """
    global _bridge
    if _bridge is None:
        if app is None:
            raise ValueError(
                "FastAPI app required for first call to get_integration_bridge"
            )
        _bridge = IntegrationBridge(app)
    return _bridge


def set_integration_bridge(bridge: IntegrationBridge) -> None:
    """Set the global integration bridge.

    Args:
        bridge: The integration bridge to set
    """
    global _bridge
    _bridge = bridge
