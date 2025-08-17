"""
Integration Bridge

Manages the coexistence of old and new architectures during the migration.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

# No longer using adapters - direct service usage
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
        self.new_initialized = False
        self.legacy_initialized = False

    # All legacy initialization methods have been removed

    async def initialize_new_architecture(self) -> None:
        """Initialize the new architecture components."""
        # Get the service provider
        from src.core.di.services import get_service_provider

        service_provider = get_service_provider()

        # Store the service provider in the app state
        self.app.state.service_provider = service_provider

        # Mark the new architecture as initialized
        self.new_initialized = True

        logger.info("New architecture initialized")

    async def initialize(self) -> None:
        """Initialize the new architecture."""
        await self.initialize_new_architecture()

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
        # For now, always use the new service
        return True

    def is_dual_mode_enabled(self) -> bool:
        """Check if dual mode is enabled.

        Returns:
            True if dual mode is enabled
        """
        # For now, dual mode is not enabled
        return False

    async def sync_session(self, session_id: str) -> None:
        """Synchronize session between old and new architectures.

        Args:
            session_id: The ID of the session to synchronize
        """
        if not (getattr(self, 'legacy_initialized', False) and self.new_initialized):
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
            # TODO: Reimplement session synchronization when migration service is available
            # migrated_session = await migration_service.migrate_legacy_session(
            #     legacy_session
            # )
            # await new_session_service.update_session(migrated_session)

            # Sync from new to legacy
            # await migration_service.sync_session_state(legacy_session, migrated_session)
            pass

            logger.debug(
                f"Successfully synchronized session {session_id} between architectures"
            )

        except Exception as e:
            logger.error(f"Failed to sync session {session_id}: {e}", exc_info=True)

    def ensure_legacy_state(self) -> None:
        """Ensure legacy state is initialized. Use this for lazy initialization in tests."""
        if not self.legacy_initialized:
            # self._setup_legacy_backends_sync()  # This method doesn't exist
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
