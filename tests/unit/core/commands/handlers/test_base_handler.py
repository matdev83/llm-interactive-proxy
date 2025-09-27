"""
Tests for Base Command Handler infrastructure.

This module tests the base command handler classes and interfaces.
"""

from typing import Any
from unittest.mock import Mock

import pytest

# Suppress Windows ProactorEventLoop ResourceWarnings for this module
pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)

from src.core.commands.handlers.base_handler import (
    BaseCommandHandler,
    CommandHandlerResult,
)
from src.core.domain.command_context import CommandContext
from src.core.domain.command_results import CommandResult
from src.core.interfaces.domain_entities_interface import ISessionState


class TestCommandHandlerResult:
    """Tests for CommandHandlerResult class."""

    def test_success_result(self) -> None:
        """Test creating a successful result."""
        result = CommandHandlerResult(
            success=True,
            message="Command executed successfully",
        )

        assert result.success is True
        assert result.message == "Command executed successfully"
        assert result.new_state is None
        assert result.additional_data == {}

    def test_failure_result(self) -> None:
        """Test creating a failure result."""
        result = CommandHandlerResult(
            success=False,
            message="Command failed",
            additional_data={"error_code": 500},
        )

        assert result.success is False
        assert result.message == "Command failed"
        assert result.new_state is None
        assert result.additional_data == {"error_code": 500}

    def test_result_with_new_state(self) -> None:
        """Test creating a result with updated state."""
        mock_state = Mock(spec=ISessionState)

        result = CommandHandlerResult(
            success=True,
            message="State updated",
            new_state=mock_state,
        )

        assert result.success is True
        assert result.message == "State updated"
        assert result.new_state is mock_state
        assert result.additional_data == {}


class TestBaseCommandHandler:
    """Tests for BaseCommandHandler class."""

    def test_initialization(self) -> None:
        """Test BaseCommandHandler initialization."""

        # Create a concrete implementation for testing
        class ConcreteHandler(BaseCommandHandler):
            def __init__(self) -> None:
                super().__init__("test-handler", ["alias1", "alias2"])

            def handle(
                self,
                param_value: Any,
                current_state: ISessionState,
                context: CommandContext | None = None,
            ) -> CommandHandlerResult:
                return CommandHandlerResult(success=True, message="test")

        handler = ConcreteHandler()

        assert handler.name == "test-handler"
        assert handler.aliases == ["alias1", "alias2"]
        assert handler.description == "Set test-handler value"
        assert handler.examples == ["!/set(test-handler=value)"]

    def test_initialization_without_aliases(self) -> None:
        """Test BaseCommandHandler initialization without aliases."""

        # Create a concrete implementation for testing
        class ConcreteHandler(BaseCommandHandler):
            def __init__(self) -> None:
                super().__init__("test-handler")

            def handle(
                self,
                param_value: Any,
                current_state: ISessionState,
                context: CommandContext | None = None,
            ) -> CommandHandlerResult:
                return CommandHandlerResult(success=True, message="test")

        handler = ConcreteHandler()

        assert handler.name == "test-handler"
        assert handler.aliases == []

    def test_can_handle_exact_match(self) -> None:
        """Test can_handle with exact parameter name match."""

        class ConcreteHandler(BaseCommandHandler):
            def handle(
                self,
                param_value: Any,
                current_state: ISessionState,
                context: CommandContext | None = None,
            ) -> CommandHandlerResult:
                return CommandHandlerResult(success=True, message="test")

        handler = ConcreteHandler("test-param", ["alias1"])

        assert handler.can_handle("test-param") is True
        assert handler.can_handle("test_param") is True
        assert (
            handler.can_handle("test param") is False
        )  # spaces are not converted to dashes

    def test_can_handle_alias_match(self) -> None:
        """Test can_handle with alias match."""

        class ConcreteHandler(BaseCommandHandler):
            def handle(
                self,
                param_value: Any,
                current_state: ISessionState,
                context: CommandContext | None = None,
            ) -> CommandHandlerResult:
                return CommandHandlerResult(success=True, message="test")

        handler = ConcreteHandler("test-param", ["alias1", "alias2"])

        assert handler.can_handle("alias1") is True
        assert (
            handler.can_handle("alias_1") is False
        )  # underscore not replaced with dash
        assert handler.can_handle("alias 1") is False  # space not replaced with dash

        assert handler.can_handle("alias2") is True

    def test_can_handle_case_insensitive(self) -> None:
        """Test can_handle is case insensitive."""

        class ConcreteHandler(BaseCommandHandler):
            def handle(
                self,
                param_value: Any,
                current_state: ISessionState,
                context: CommandContext | None = None,
            ) -> CommandHandlerResult:
                return CommandHandlerResult(success=True, message="test")

        handler = ConcreteHandler("Test-Param", ["Alias-One"])

        assert handler.can_handle("test-param") is True
        assert handler.can_handle("TEST-PARAM") is True
        assert handler.can_handle("Test-Param") is True

        assert handler.can_handle("alias-one") is True
        assert handler.can_handle("ALIAS-ONE") is True

    def test_can_handle_no_match(self) -> None:
        """Test can_handle returns False for no match."""

        class ConcreteHandler(BaseCommandHandler):
            def handle(
                self,
                param_value: Any,
                current_state: ISessionState,
                context: CommandContext | None = None,
            ) -> CommandHandlerResult:
                return CommandHandlerResult(success=True, message="test")

        handler = ConcreteHandler("test-param", ["alias1"])

        assert handler.can_handle("other-param") is False
        assert handler.can_handle("different") is False
        assert handler.can_handle("") is False

    def test_convert_to_legacy_result_success(self) -> None:
        """Test convert_to_legacy_result for successful result."""

        class ConcreteHandler(BaseCommandHandler):
            def handle(
                self,
                param_value: Any,
                current_state: ISessionState,
                context: CommandContext | None = None,
            ) -> CommandHandlerResult:
                return CommandHandlerResult(success=True, message="test")

        handler = ConcreteHandler("test-handler")

        result = CommandHandlerResult(
            success=True,
            message="Success message",
        )

        handled, message_or_result, requires_auth = handler.convert_to_legacy_result(
            result
        )

        assert handled is True
        assert message_or_result == "Success message"
        assert requires_auth is False

    def test_convert_to_legacy_result_failure(self) -> None:
        """Test convert_to_legacy_result for failed result."""

        class ConcreteHandler(BaseCommandHandler):
            def handle(
                self,
                param_value: Any,
                current_state: ISessionState,
                context: CommandContext | None = None,
            ) -> CommandHandlerResult:
                return CommandHandlerResult(success=True, message="test")

        handler = ConcreteHandler("test-handler")

        result = CommandHandlerResult(
            success=False,
            message="Error message",
        )

        handled, message_or_result, requires_auth = handler.convert_to_legacy_result(
            result
        )

        assert handled is True
        assert isinstance(message_or_result, CommandResult)
        assert message_or_result.success is False
        assert message_or_result.message == "Error message"
        assert message_or_result.name == "set"  # default command name
        assert requires_auth is False

    def test_convert_to_legacy_result_with_command_name(self) -> None:
        """Test convert_to_legacy_result with custom command name."""

        class ConcreteHandler(BaseCommandHandler):
            def handle(
                self,
                param_value: Any,
                current_state: ISessionState,
                context: CommandContext | None = None,
            ) -> CommandHandlerResult:
                return CommandHandlerResult(success=True, message="test")

        handler = ConcreteHandler("test-handler")

        result = CommandHandlerResult(
            success=False,
            message="Error message",
        )

        handled, message_or_result, requires_auth = handler.convert_to_legacy_result(
            result, "custom"
        )

        assert handled is True
        assert isinstance(message_or_result, CommandResult)
        assert message_or_result.success is False
        assert message_or_result.message == "Error message"
        assert message_or_result.name == "custom"
        assert requires_auth is False


class TestICommandHandlerInterface:
    """Tests for ICommandHandler interface compliance."""

    def test_base_command_handler_implements_interface(self) -> None:
        """Test that BaseCommandHandler implements ICommandHandler."""

        class ConcreteHandler(BaseCommandHandler):
            def handle(
                self,
                param_value: Any,
                current_state: ISessionState,
                context: CommandContext | None = None,
            ) -> CommandHandlerResult:
                return CommandHandlerResult(success=True, message="test")

        handler = ConcreteHandler("test-handler")

        # Check that all abstract methods are implemented
        assert hasattr(handler, "name")
        assert hasattr(handler, "aliases")
        assert hasattr(handler, "description")
        assert hasattr(handler, "examples")
        assert hasattr(handler, "can_handle")
        assert hasattr(handler, "handle")
        assert hasattr(handler, "convert_to_legacy_result")

        # Test that they can be called
        assert handler.name == "test-handler"
        assert handler.aliases == []
        assert handler.description == "Set test-handler value"
        assert handler.examples == ["!/set(test-handler=value)"]
        assert handler.can_handle("test-handler") is True

        # handle should work since it's implemented
        mock_state = Mock(spec=ISessionState)
        result = handler.handle("test-value", mock_state)
        assert result.success is True
        assert result.message == "test"

    def test_custom_handler_inheritance(self) -> None:
        """Test creating a custom handler that inherits from BaseCommandHandler."""

        class CustomHandler(BaseCommandHandler):
            def __init__(self) -> None:
                super().__init__("custom-param", ["custom", "alias"])

            @property
            def description(self) -> str:
                return "Custom parameter handler"

            @property
            def examples(self) -> list[str]:
                return ["!/set(custom-param=value)", "!/set(custom=other)"]

            def handle(
                self,
                param_value: Any,
                current_state: ISessionState,
                context: CommandContext | None = None,
            ) -> CommandHandlerResult:
                return CommandHandlerResult(
                    success=True,
                    message=f"Set custom-param to {param_value}",
                    new_state=current_state,
                )

        handler = CustomHandler()

        # Test basic properties
        assert handler.name == "custom-param"
        assert handler.aliases == ["custom", "alias"]
        assert handler.description == "Custom parameter handler"
        assert handler.examples == ["!/set(custom-param=value)", "!/set(custom=other)"]

        # Test can_handle with name and aliases
        assert handler.can_handle("custom-param") is True
        assert handler.can_handle("custom") is True
        assert handler.can_handle("alias") is True
        assert handler.can_handle("other") is False

        # Test handle method
        mock_state = Mock(spec=ISessionState)
        result = handler.handle("test-value", mock_state)

        assert result.success is True
        assert result.message == "Set custom-param to test-value"
        assert result.new_state is mock_state
