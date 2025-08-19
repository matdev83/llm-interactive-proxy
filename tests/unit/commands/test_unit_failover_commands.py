
from unittest.mock import Mock

import pytest
from src.core.domain.commands.failover_commands import (
    CreateFailoverRouteCommand,
    DeleteFailoverRouteCommand,
    ListFailoverRoutesCommand,
)
from src.core.domain.session import BackendConfiguration, Session, SessionState


@pytest.fixture
def mock_session() -> Mock:
    """Creates a mock session object with a default state."""
    mock = Mock(spec=Session)
    mock.state = SessionState(
        backend_config=BackendConfiguration()
    )
    return mock

@pytest.mark.asyncio
async def test_create_failover_route(mock_session: Mock):
    # Arrange
    command = CreateFailoverRouteCommand()
    args = {"name": "myroute", "policy": "k"}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is True
    assert "Failover route 'myroute' created" in result.message
    # The command modifies session.state directly, so we check the mock
    assert "myroute" in mock_session.state.backend_config.failover_routes

@pytest.mark.asyncio
async def test_delete_failover_route(mock_session: Mock):
    # Arrange
    command = DeleteFailoverRouteCommand()
    # First, create a route to delete
    create_command = CreateFailoverRouteCommand()
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
async def test_list_failover_routes(mock_session: Mock):
    # Arrange
    command = ListFailoverRoutesCommand()
    create_command = CreateFailoverRouteCommand()
    await create_command.execute({"name": "route1", "policy": "k"}, mock_session)
    await create_command.execute({"name": "route2", "policy": "m"}, mock_session)

    # Act
    result = await command.execute({}, mock_session)

    # Assert
    assert result.success is True
    assert "Failover routes:" in result.message
    assert "route1:k" in result.message
    assert "route2:m" in result.message
