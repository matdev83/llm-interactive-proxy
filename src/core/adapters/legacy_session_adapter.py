from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from src.core.domain.session import Session as NewSession
from src.core.domain.session import SessionInteraction as NewSessionInteraction
from src.core.domain.session import SessionState
from src.core.interfaces.domain_entities import ISession, ISessionState

# Conditional imports for type checking only
if TYPE_CHECKING:
    from src.session import Session as LegacySession


class LegacySessionAdapter(ISession):
    """Adapter that wraps a legacy Session to implement ISession interface."""
    
    def __init__(self, legacy_session: LegacySession):
        """Initialize the adapter with a legacy session.
        
        Args:
            legacy_session: The legacy session to wrap
        """
        self._legacy_session = legacy_session
        self._new_session: NewSession | None = None
    
    @property
    def session_id(self) -> str:
        """Get the session ID."""
        return self._legacy_session.session_id
    
    @property
    def id(self) -> str:
        """Get the unique identifier for this entity."""
        return self.session_id
    
    @property
    def state(self) -> ISessionState:
        """Get the session state."""
        if self._new_session is None:
            self._new_session = self._convert_to_new_session()
        return self._new_session.state
    
    @property
    def created_at(self) -> datetime:
        """Get the session creation time."""
        # Legacy sessions don't track creation time, use current time as fallback
        return datetime.now()
    
    @property
    def last_active_at(self) -> datetime:
        """Get the time of last activity in this session."""
        # Legacy sessions don't track last active time, use current time as fallback
        return datetime.now()
    
    @property
    def history(self) -> list[Any]:
        """Get the session history."""
        return self._legacy_session.history
    
    @property
    def agent(self) -> str | None:
        """Get the agent type."""
        return getattr(self._legacy_session, 'agent', None)
    
    @agent.setter
    def agent(self, value: str | None) -> None:
        """Set the agent type."""
        self._legacy_session.agent = value
    
    def add_interaction(self, interaction: Any) -> None:
        """Add an interaction to the session."""
        self._legacy_session.add_interaction(interaction)
    
    def update_state(self, state: ISessionState) -> None:
        """Update the session state."""
        # Convert ISessionState back to legacy proxy state
        # This is a simplified implementation
        proxy_state = self._legacy_session.proxy_state
        
        # Update what we can from the new state
        if hasattr(state, 'backend_config'):
            backend_config = state.backend_config
            if hasattr(backend_config, 'backend_type'):
                proxy_state.override_backend = backend_config.backend_type
            if hasattr(backend_config, 'model'):
                proxy_state.override_model = backend_config.model
        
        if hasattr(state, 'project'):
            proxy_state.project = state.project
    
    def _convert_to_new_session(self) -> NewSession:
        """Convert the legacy session to a new session."""
        from src.core.domain.configuration import (
            BackendConfiguration,
            LoopDetectionConfiguration,
            ReasoningConfiguration,
        )
        
        # Extract configuration from legacy proxy state
        proxy_state = self._legacy_session.proxy_state
        
        # Create backend configuration
        backend_config = BackendConfiguration(
            backend_type=proxy_state.override_backend or "openrouter",
            model=proxy_state.override_model or "gpt-3.5-turbo",
            api_url=getattr(proxy_state, 'openai_url', None),
            interactive_mode=True,
            failover_routes={},
        )
        
        # Create reasoning configuration
        reasoning_config = ReasoningConfiguration(
            reasoning_effort=proxy_state.reasoning_effort,
            thinking_budget=proxy_state.thinking_budget,
            temperature=proxy_state.temperature,
        )
        
        # Create loop detection configuration
        loop_config = LoopDetectionConfiguration(
            loop_detection_enabled=proxy_state.loop_detection_enabled or False,
            tool_loop_detection_enabled=proxy_state.tool_loop_detection_enabled or False,
            min_pattern_length=50,
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
        return NewSession(
            session_id=self._legacy_session.session_id,
            state=session_state,
            history=[
                NewSessionInteraction(
                    prompt=interaction.prompt,
                    handler=interaction.handler,
                    backend=interaction.backend,
                    model=interaction.model,
                    project=interaction.project,
                    parameters=interaction.parameters,
                    response=interaction.response,
                    usage=interaction.usage.dict() if interaction.usage else None,
                    timestamp=datetime.now(timezone.utc),  # Default timestamp since legacy doesn't have it
                )
                for interaction in self._legacy_session.history
            ] if self._legacy_session.history else None,
        )
    
    def update_from_new_session(self, new_session: NewSession) -> None:
        """Update the legacy session from a new session."""
        # Update proxy state from new session state
        proxy_state = self._legacy_session.proxy_state
        
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
        self._legacy_session.history = new_session.history
        
        # Update cached new session
        self._new_session = new_session


def create_legacy_session_adapter(legacy_session: LegacySession) -> LegacySessionAdapter:
    """Create a legacy session adapter.
    
    Args:
        legacy_session: The legacy session to wrap
        
    Returns:
        A legacy session adapter
    """
    return LegacySessionAdapter(legacy_session)