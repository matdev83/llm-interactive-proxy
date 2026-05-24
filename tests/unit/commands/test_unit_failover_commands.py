from unittest.mock import Mock

import pytest
from src.core.domain.commands.failover_commands import (
    CreateFailoverRouteCommand,
    DeleteFailoverRouteCommand,
    ListFailoverRoutesCommand,
)
from src.core.domain.session import BackendConfiguration, Session, SessionState
from src.core.interfaces.state_provider_interface import (
    ISecureStateAccess,
    ISecureStateModification,
)


@pytest.fixture
def mock_state_reader() -> ISecureStateAccess:
    """Returns a mock state reader for tests."""
    mock_reader = Mock(spec=ISecureStateAccess)
    # Set up default return values for state reader methods
    mock_reader.get_command_prefix.return_value = "!/"
    mock_reader.get_api_key_redaction_enabled.return_value = True
    mock_reader.get_disable_interactive_commands.return_value = False
    mock_reader.get_failover_routes.return_value = []
    return mock_reader


@pytest.fixture
def mock_state_modifier() -> ISecureStateModification:
    """Returns a mock state modifier for tests."""
    mock_modifier = Mock(spec=ISecureStateModification)
    return mock_modifier


@pytest.fixture
def mock_session() -> Mock:
    """Creates a mock session object with a default state."""
    mock = Mock(spec=Session)
    mock.state = SessionState(backend_config=BackendConfiguration())
    return mock


@pytest.mark.asyncio
async def test_create_failover_route(
    mock_session: Mock,
    mock_state_reader: ISecureStateAccess,
    mock_state_modifier: ISecureStateModification,
):
    # Arrange
    command = CreateFailoverRouteCommand(
        state_reader=mock_state_reader, state_modifier=mock_state_modifier
    )
    args = {"name": "myroute", "policy": "k"}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is True
    assert "Failover route 'myroute' created" in result.message
    # The command modifies session.state directly, so we check the mock
    assert "myroute" in mock_session.state.backend_config.failover_routes


@pytest.mark.asyncio
async def test_create_failover_route_does_not_toggle_interactive_flag(
    mock_session: Mock,
    mock_state_reader: ISecureStateAccess,
    mock_state_modifier: ISecureStateModification,
) -> None:
    """Ensure creating a route leaves the interactive flag untouched."""

    command = CreateFailoverRouteCommand(
        state_reader=mock_state_reader, state_modifier=mock_state_modifier
    )
    # The interactive flag should remain whatever it was before execution.
    assert mock_session.state.interactive_just_enabled is False

    await command.execute({"name": "route", "policy": "k"}, mock_session)

    assert mock_session.state.interactive_just_enabled is False


@pytest.mark.asyncio
async def test_delete_failover_route(
    mock_session: Mock,
    mock_state_reader: ISecureStateAccess,
    mock_state_modifier: ISecureStateModification,
):
    # Arrange
    command = DeleteFailoverRouteCommand(
        state_reader=mock_state_reader, state_modifier=mock_state_modifier
    )
    # First, create a route to delete
    create_command = CreateFailoverRouteCommand(
        state_reader=mock_state_reader, state_modifier=mock_state_modifier
    )
    await create_command.execute({"name": "myroute", "policy": "k"}, mock_session)
    assert "myroute" in mock_session.state.backend_config.failover_routes

    # Act
    args = {"name": "myroute"}
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is True
    assert "Failover route 'myroute' deleted" in result.message
    assert "myroute" not in mock_session.state.backend_config.failover_routes


@pytest.mark.asyncio
async def test_list_failover_routes(
    mock_session: Mock,
    mock_state_reader: ISecureStateAccess,
    mock_state_modifier: ISecureStateModification,
):
    # Arrange
    command = ListFailoverRoutesCommand(
        state_reader=mock_state_reader, state_modifier=mock_state_modifier
    )
    create_command = CreateFailoverRouteCommand(
        state_reader=mock_state_reader, state_modifier=mock_state_modifier
    )
    await create_command.execute({"name": "route1", "policy": "k"}, mock_session)
    await create_command.execute({"name": "route2", "policy": "m"}, mock_session)

    # Act
    result = await command.execute({}, mock_session)

    # Assert
    assert result.success is True
    assert "Failover routes:" in result.message
    assert "route1:k" in result.message
    assert "route2:m" in result.message
