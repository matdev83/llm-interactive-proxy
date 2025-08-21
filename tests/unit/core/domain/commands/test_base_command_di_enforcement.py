"""
Tests for the BaseCommand DI enforcement mechanisms.
"""

from collections.abc import Mapping
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.session import Session


class StatelessCommand(BaseCommand):
    """A stateless command for testing."""

    @property
    def name(self) -> str:
        return "stateless"

    @property
    def description(self) -> str:
        return "A stateless command for testing"

    @property
    def format(self) -> str:
        return "stateless"

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Execute the command."""
        return CommandResult(
            success=True,
            message="Stateless command executed",
            name=self.name,
            modified_session=session,
        )


class StatefulCommand(BaseCommand):
    """A stateful command for testing."""

    def __init__(self, dependency1: str, dependency2: str):
        """Initialize the command with dependencies."""
        self._dependency1 = dependency1
        self._dependency2 = dependency2

    @property
    def name(self) -> str:
        return "stateful"

    @property
    def description(self) -> str:
        return "A stateful command for testing"

    @property
    def format(self) -> str:
        return "stateful"

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Execute the command."""
        self._validate_di_usage()
        return CommandResult(
            success=True,
            message=f"Stateful command executed with {self._dependency1} and {self._dependency2}",
            name=self.name,
            modified_session=session,
        )


class TestBaseCommandDIEnforcement:
    """Tests for the BaseCommand DI enforcement mechanisms."""

    def test_stateless_command_instantiation(self):
        """Test that a stateless command can be instantiated directly."""
        # This should work without any issues
        command = StatelessCommand()
        assert command.name == "stateless"

    def test_stateful_command_instantiation_with_dependencies(self):
        """Test that a stateful command can be instantiated with dependencies."""
        # This should work when dependencies are provided
        command = StatefulCommand("dep1", "dep2")
        assert command.name == "stateful"
        assert command._dependency1 == "dep1"
        assert command._dependency2 == "dep2"
