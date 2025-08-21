from unittest.mock import Mock

import pytest
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.commands.help_command import HelpCommand
from src.core.domain.session import Session


class MockCommand(BaseCommand):
    def __init__(self, name, description, format_str, examples):
        self.name = name
        self.description = description
        self.format = format_str
        self.examples = examples

    async def execute(self, args, session, context):
        pass


@pytest.fixture
def command() -> HelpCommand:
    return HelpCommand()


@pytest.fixture
def mock_session() -> Mock:
    return Mock(spec=Session)


@pytest.fixture
def mock_handlers() -> dict:
    return {
        "help": MockCommand("help", "Shows help", "help(<cmd>)", ["!/help"]),
        "set": MockCommand("set", "Sets a value", "set(k=v)", ["!/set(foo=bar)"]),
    }


@pytest.mark.asyncio
async def test_help_general(
    command: HelpCommand, mock_session: Mock, mock_handlers: dict
):
    # Arrange
    context = {"handlers": mock_handlers}

    # Act
    result = await command.execute({}, mock_session, context)

    # Assert
    assert result.success is True
    assert "Available commands:" in result.message
    assert "- help - Shows help" in result.message
    assert "- set - Sets a value" in result.message


@pytest.mark.asyncio
async def test_help_specific_command(
    command: HelpCommand, mock_session: Mock, mock_handlers: dict
):
    # Arrange
    context = {"handlers": mock_handlers}
    args = {"set": True}

    # Act
    result = await command.execute(args, mock_session, context)

    # Assert
    assert result.success is True
    assert "set - Sets a value" in result.message
    assert "Format: set(k=v)" in result.message
    assert "Examples: !/set(foo=bar)" in result.message


@pytest.mark.asyncio
async def test_help_unknown_command(
    command: HelpCommand, mock_session: Mock, mock_handlers: dict
):
    # Arrange
    context = {"handlers": mock_handlers}
    args = {"unknown": True}

    # Act
    result = await command.execute(args, mock_session, context)

    # Assert
    assert result.success is False
    assert "Unknown command: unknown" in result.message
