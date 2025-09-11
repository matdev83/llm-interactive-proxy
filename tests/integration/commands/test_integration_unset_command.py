from typing import Any

import pytest
from src.core.domain.session import (
    BackendConfiguration,
    ReasoningConfiguration,
    Session,
    SessionState,
)
from src.core.interfaces.session_service_interface import ISessionService
from src.core.interfaces.state_provider_interface import (
    ISecureStateAccess,
    ISecureStateModification,
)


class MockSessionService(ISessionService, ISecureStateAccess, ISecureStateModification):
    """A mock session service that implements both session service and secure state interfaces."""
    
    def __init__(self, session: Session):
        self._session = session
        # Initialize default values for state that would normally come from app state
        self._command_prefix = "!/"
        self._api_key_redaction_enabled = True
        self._disable_interactive_commands = False
        self._failover_routes: list[dict[str, Any]] = []
        # Store sessions in a dictionary
        self._sessions = {session.session_id: session}

    # ISessionService methods
    async def get_session(self, session_id: str) -> Session:
        if session_id not in self._sessions:
            # Create a new session if it doesn't exist
            new_session = Session(
                session_id=session_id,
                state=SessionState(
                    backend_config=BackendConfiguration(
                        backend_type="default_backend",
                        model="default_model"
                    ),
                    reasoning_config=ReasoningConfiguration(temperature=0.7)
                )
            )
            self._sessions[session_id] = new_session
            return new_session
        return self._sessions[session_id]

    async def create_session(self, session_id: str) -> Session:
        if session_id in self._sessions:
            raise ValueError(f"Session with ID {session_id} already exists.")
        session = Session(
            session_id=session_id,
            state=SessionState(
                backend_config=BackendConfiguration(
                    backend_type="default_backend",
                    model="default_model"
                ),
                reasoning_config=ReasoningConfiguration(temperature=0.7)
            )
        )
        self._sessions[session_id] = session
        return session

    async def get_or_create_session(self, session_id: str | None = None) -> Session:
        if session_id is None:
            session_id = f"test-session-{len(self._sessions) + 1}"
        return await self.get_session(session_id)

    async def update_session(self, session: Session) -> None:
        self._sessions[session.session_id] = session

    async def update_session_backend_config(
        self, session_id: str, backend_type: str, model: str
    ) -> None:
        session = await self.get_session(session_id)
        new_backend_config = session.state.backend_config.with_backend_type(backend_type).with_model(model)
        session.state = session.state.with_backend_config(new_backend_config)
        self._sessions[session_id] = session

    async def delete_session(self, session_id: str) -> bool:
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False

    async def get_all_sessions(self) -> list[Session]:
        return list(self._sessions.values())

    # ISecureStateAccess methods
    def get_command_prefix(self) -> str | None:
        return self._command_prefix

    def get_api_key_redaction_enabled(self) -> bool:
        return self._api_key_redaction_enabled

    def get_disable_interactive_commands(self) -> bool:
        return self._disable_interactive_commands

    def get_failover_routes(self) -> list[dict[str, Any]] | None:
        return self._failover_routes

    # ISecureStateModification methods
    def update_command_prefix(self, prefix: str) -> None:
        self._command_prefix = prefix

    def update_api_key_redaction(self, enabled: bool) -> None:
        self._api_key_redaction_enabled = enabled

    def update_interactive_commands(self, disabled: bool) -> None:
        self._disable_interactive_commands = disabled

    def update_failover_routes(self, routes: list[dict[str, Any]]) -> None:
        self._failover_routes = routes


# Helper function to simulate running a command, adapted for unset command tests
async def run_command(command_string: str, initial_state: SessionState = None) -> str:
    """Run a command and return the result message."""
    from src.core.commands.parser import CommandParser
    from src.core.commands.service import NewCommandService
    from src.core.domain.chat import ChatMessage
    from src.core.services.command_processor import (
        CommandProcessor as CoreCommandProcessor,
    )

    # Create a Session object to hold the state
    initial_state = initial_state or SessionState()
    session = Session(session_id="test_session", state=initial_state)

    session_service = MockSessionService(session=session)
    command_parser = CommandParser()
    service = NewCommandService(session_service, command_parser)
    processor = CoreCommandProcessor(service)

    messages = [ChatMessage(role="user", content=command_string)]

    result = await processor.process_messages(messages, session_id="test_session")

    if result.command_results:
        return result.command_results[0].message

    return ""


@pytest.fixture
def initial_state() -> SessionState:
    """Provides a session state with non-default values to be unset."""
    return SessionState(
        backend_config=BackendConfiguration(
            backend_type="default_backend",
            model="default_model",
            override_backend="custom_backend",
            override_model="custom_model",
        ),
        reasoning_config=ReasoningConfiguration(temperature=0.9),
        project="test_project",
    )


@pytest.mark.asyncio
async def test_unset_temperature_snapshot(initial_state: SessionState, snapshot):
    """Snapshot test for unsetting temperature."""
    # Arrange
    command_string = "!/unset(temperature)"

    # Act
    output_message = await run_command(command_string, initial_state)

    # Assert
    snapshot.assert_match(output_message, "unset_temperature_output")


@pytest.mark.asyncio
async def test_unset_model_snapshot(initial_state: SessionState, snapshot):
    """Snapshot test for unsetting the model."""
    # Arrange
    command_string = "!/unset(model)"

    # Act
    output_message = await run_command(command_string, initial_state)

    # Assert
    snapshot.assert_match(output_message, "unset_model_output")


@pytest.mark.asyncio
async def test_unset_multiple_params_snapshot(initial_state: SessionState, snapshot):
    """Snapshot test for unsetting multiple parameters at once."""
    # Arrange
    command_string = "!/unset(project, temperature)"

    # Act
    output_message = await run_command(command_string, initial_state)

    # Assert
    snapshot.assert_match(output_message, "unset_multiple_params_output")


@pytest.mark.asyncio
async def test_unset_unknown_param_snapshot(initial_state: SessionState, snapshot):
    """Snapshot test for unsetting an unknown parameter."""
    # Arrange
    command_string = "!/unset(nonexistent)"

    # Act
    output_message = await run_command(command_string, initial_state)

    # Assert
    snapshot.assert_match(output_message, "unset_unknown_param_output")