"""
Tests for the CommandFactory class.
"""

from unittest.mock import Mock

import pytest
from src.core.di.container import ServiceProvider
from src.core.domain.commands.command_factory import CommandFactory
from src.core.domain.commands.help_command import HelpCommand


class TestCommandFactory:
    """Tests for the CommandFactory class."""

    def test_create_success(self):
        """Test that the factory can create a command."""
        # Arrange
        mock_provider = Mock(spec=ServiceProvider)
        mock_provider.get_service.return_value = HelpCommand()
        factory = CommandFactory(mock_provider)

        # Act
        command = factory.create(HelpCommand)

        # Assert
        assert isinstance(command, HelpCommand)
        mock_provider.get_service.assert_called_once_with(HelpCommand)

    def test_create_error(self):
        """Test that the factory raises an error if the command cannot be created."""
        # Arrange
        mock_provider = Mock(spec=ServiceProvider)
        mock_provider.get_service.side_effect = RuntimeError("Test error")
        factory = CommandFactory(mock_provider)

        # Act & Assert
        with pytest.raises(RuntimeError):
            factory.create(HelpCommand)

    def test_register_factory(self):
        """Test that the factory can be registered in the DI container."""
        # Arrange
        mock_services = Mock()

        # Act
        CommandFactory.register_factory(mock_services)

        # Assert
        mock_services.add_singleton_factory.assert_called_once()
        # Check that the first argument is CommandFactory
        assert mock_services.add_singleton_factory.call_args[0][0] == CommandFactory
