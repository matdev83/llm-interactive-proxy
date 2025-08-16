"""
Session Migration Service

Handles the migration of session data from legacy format to new SOLID architecture.
This service provides utilities for converting between legacy and new session formats.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.domain.configuration import (
    BackendConfig,
    LoopDetectionConfig,
    ReasoningConfig,
)
from src.core.domain.session import Session as NewSession
from src.core.domain.session import SessionState
from src.core.interfaces.session_service import ISessionService
from src.session import Session as LegacySession

logger = logging.getLogger(__name__)


class SessionMigrationService:
    """Service for migrating sessions between legacy and new formats."""
    
    def __init__(self, new_session_service: ISessionService):
        """Initialize the migration service.
        
        Args:
            new_session_service: The new session service implementation
        """
        self._new_session_service = new_session_service
    
    async def migrate_legacy_session(self, legacy_session: LegacySession) -> NewSession:
        """Migrate a legacy session to the new format.
        
        Args:
            legacy_session: The legacy session to migrate
            
        Returns:
            A new session with migrated data
        """
        logger.debug(f"Migrating legacy session: {legacy_session.session_id}")
        
        # Extract configuration from legacy proxy state
        proxy_state = legacy_session.proxy_state
        
        # Create backend configuration
        backend_config = BackendConfig(
            backend_type=proxy_state.override_backend or "openrouter",
            model=proxy_state.override_model or "gpt-3.5-turbo",
            api_url=getattr(proxy_state, 'openai_url', None),
            interactive_mode=True,  # Default for legacy sessions
            failover_routes={},  # Legacy sessions don't have complex failover
        )
        
        # Create reasoning configuration
        reasoning_config = ReasoningConfig(
            reasoning_effort=proxy_state.reasoning_effort,
            thinking_budget=proxy_state.thinking_budget,
            temperature=proxy_state.temperature,
        )
        
        # Create loop detection configuration
        loop_detection_enabled = getattr(proxy_state, 'loop_detection_enabled', None)
        tool_loop_detection_enabled = getattr(proxy_state, 'tool_loop_detection_enabled', None)
        
        loop_config = LoopDetectionConfig(
            loop_detection_enabled=loop_detection_enabled if loop_detection_enabled is not None else True,
            tool_loop_detection_enabled=tool_loop_detection_enabled if tool_loop_detection_enabled is not None else True,
            min_pattern_length=50,  # Default values
            max_pattern_length=500,
        )
        
        # Create session state
        session_state = SessionState(
            backend_config=backend_config,
            reasoning_config=reasoning_config,
            loop_config=loop_config,
            project=proxy_state.project,
            project_dir=proxy_state.project_dir,
        )
        
        # Create new session
        new_session = NewSession(
            session_id=legacy_session.session_id,
            state=session_state,
            history=legacy_session.history,
        )
        
        # Set agent if present
        if hasattr(legacy_session, 'agent') and legacy_session.agent:
            new_session.agent = legacy_session.agent
        
        return new_session
    
    async def sync_session_state(
        self, 
        legacy_session: LegacySession, 
        new_session: NewSession
    ) -> None:
        """Synchronize state between legacy and new session formats.
        
        Args:
            legacy_session: The legacy session to update
            new_session: The new session with updated state
        """
        logger.debug(f"Syncing session state: {legacy_session.session_id}")
        
        # Update legacy proxy state from new session state
        proxy_state = legacy_session.proxy_state
        
        # Update backend configuration
        backend_config = new_session.state.backend_config
        proxy_state.override_backend = backend_config.backend_type
        proxy_state.override_model = backend_config.model
        if backend_config.api_url:
            proxy_state.openai_url = backend_config.api_url
        
        # Update reasoning configuration
        reasoning_config = new_session.state.reasoning_config
        proxy_state.reasoning_effort = reasoning_config.reasoning_effort
        proxy_state.thinking_budget = reasoning_config.thinking_budget
        proxy_state.temperature = reasoning_config.temperature
        
        # Update loop detection configuration
        loop_config = new_session.state.loop_config
        proxy_state.loop_detection_enabled = loop_config.loop_detection_enabled
        proxy_state.tool_loop_detection_enabled = loop_config.tool_loop_detection_enabled
        
        # Update project settings
        proxy_state.project = new_session.state.project
        proxy_state.project_dir = new_session.state.project_dir
        
        # Update history
        legacy_session.history = new_session.history
        
        # Update agent
        if hasattr(new_session, 'agent'):
            legacy_session.agent = new_session.agent
    
    async def create_hybrid_session(self, session_id: str) -> tuple[LegacySession, NewSession]:
        """Create both legacy and new session objects that stay in sync.
        
        Args:
            session_id: The session ID
            
        Returns:
            A tuple of (legacy_session, new_session)
        """
        logger.debug(f"Creating hybrid session: {session_id}")
        
        # Create a new session using the new service
        new_session = await self._new_session_service.create_session(session_id)
        
        # Create a legacy session with default proxy state
        # Note: This is only for backward compatibility and will be removed in the future
        # Using ProxyState but with a warning that it's deprecated
        import warnings

        from src.proxy_logic import ProxyState
        from src.session import Session as LegacySession
        warnings.warn(
            "Using ProxyState in SessionMigrationService is deprecated and will be removed in a future version.",
            DeprecationWarning,
            stacklevel=2
        )
        
        proxy_state = ProxyState()
        legacy_session = LegacySession(session_id=session_id, proxy_state=proxy_state)
        
        # Sync the initial state
        await self.sync_session_state(legacy_session, new_session)
        
        return legacy_session, new_session
    
    def extract_session_metrics(self, session: LegacySession | NewSession) -> dict[str, Any]:
        """Extract metrics from a session for monitoring.
        
        Args:
            session: Either legacy or new session
            
        Returns:
            Dictionary of session metrics
        """
        metrics = {
            "session_id": session.session_id,
            "history_length": len(session.history),
            "agent": getattr(session, 'agent', None),
        }
        
        if isinstance(session, LegacySession):
            metrics.update({
                "session_type": "legacy",
                "backend": session.proxy_state.override_backend,
                "model": session.proxy_state.override_model,
                "project": session.proxy_state.project,
            })
        else:
            metrics.update({
                "session_type": "new",
                "backend": session.state.backend_config.backend_type,
                "model": session.state.backend_config.model,
                "project": session.state.project,
            })
        
        return metrics


def create_session_migration_service(session_service: ISessionService) -> SessionMigrationService:
    """Create a session migration service.
    
    Args:
        session_service: The new session service
        
    Returns:
        A session migration service
    """
    return SessionMigrationService(session_service)