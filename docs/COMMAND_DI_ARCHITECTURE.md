# Command DI Architecture

## Overview

This document describes the Dependency Injection (DI) architecture for commands in the proxy. The architecture ensures that:

1. Commands are properly instantiated through the DI container
2. Commands have access to the dependencies they need
3. Direct instantiation of commands that require dependencies is prevented
4. The command system is consistently using DI throughout the codebase

## Architecture Components

### CommandRegistry

The `CommandRegistry` is a central registry for all commands. It is responsible for:

- Storing command instances by name
- Providing access to commands by name
- Ensuring that commands are properly instantiated through DI

The registry is a singleton that is accessible globally through static methods:

```python
from src.core.services.command_service import CommandRegistry

# Get the global registry instance
registry = CommandRegistry.get_instance()

# Get a command by name
command = registry.get("set")

# Get all commands
commands = registry.get_all()
```

### BaseCommand

The `BaseCommand` class is the base class for all commands. It provides:

- Common functionality for all commands
- DI validation through the `_validate_di_usage()` method
- A consistent interface for command execution

### StatelessCommandBase and StatefulCommandBase

These base classes extend `BaseCommand` to provide:

- `StatelessCommandBase`: For commands that don't require state access
- `StatefulCommandBase`: For commands that require state access (via `ISecureStateAccess` and `ISecureStateModification`)

### CommandParser

The `CommandParser` is responsible for parsing commands from messages. It:

- Gets commands from the `CommandRegistry` (DI container)
- Falls back to auto-discovery only if the registry is not available
- Processes commands in messages

### Command Registration

Commands are registered in the DI container in `src/core/services/command_registration.py`. This file:

- Registers all stateless commands
- Registers all stateful commands with their dependencies
- Ensures that all commands are available through the DI container

## Command Types

### Stateless Commands

Stateless commands don't require any dependencies. They are registered in the DI container as:

```python
services.add_singleton_factory(
    HelpCommand,
    lambda _: HelpCommand(),
)
```

Examples of stateless commands:
- `HelpCommand`
- `HelloCommand`
- `ModelCommand`
- `OneoffCommand`
- `ProjectCommand`
- `PwdCommand`
- `TemperatureCommand`
- `LoopDetectionCommand`

### Stateful Commands

Stateful commands require dependencies, such as state access or modification. They are registered in the DI container as:

```python
services.add_singleton_factory(
    SetCommand,
    lambda provider: SetCommand(
        provider.get_service(ISecureStateAccess),
        provider.get_service(ISecureStateModification),
    ),
)
```

Examples of stateful commands:
- `SetCommand`
- `UnsetCommand`
- `CreateFailoverRouteCommand`
- `DeleteFailoverRouteCommand`
- `ListFailoverRoutesCommand`
- `OpenAIUrlCommand`

## DI Validation

The `_validate_di_usage()` method in `BaseCommand` ensures that commands are properly instantiated through the DI container. It:

1. Examines the command's constructor to determine if it requires dependencies
2. Checks if the required dependencies are set
3. Raises a `RuntimeError` if the command was not instantiated properly

This validation is called:
- When a command is registered in the `CommandRegistry`
- When a command is executed (in the `execute()` method)

## Creating a New Command

### Stateless Command

To create a new stateless command:

1. Create a new file in `src/core/domain/commands/`
2. Extend `StatelessCommandBase` and `BaseCommand`
3. Implement the required properties and methods
4. Register the command in `src/core/services/command_registration.py`

Example:

```python
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.commands.secure_base_command import StatelessCommandBase

class MyCommand(StatelessCommandBase, BaseCommand):
    def __init__(self):
        """Initialize without state services."""
        StatelessCommandBase.__init__(self)

    @property
    def name(self) -> str:
        return "my-command"

    @property
    def format(self) -> str:
        return "my-command(param=value)"

    @property
    def description(self) -> str:
        return "My command description"

    @property
    def examples(self) -> list[str]:
        return ["!/my-command(param=value)"]

    async def execute(self, args: Mapping[str, Any], session: Session, context: Any = None) -> CommandResult:
        # Command implementation
        return CommandResult(
            name=self.name,
            success=True,
            message="Command executed successfully",
        )
```

### Stateful Command

To create a new stateful command:

1. Create a new file in `src/core/domain/commands/`
2. Extend `StatefulCommandBase` and `BaseCommand`
3. Implement the required properties and methods
4. Register the command in `src/core/services/command_registration.py`

Example:

```python
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.commands.secure_base_command import StatefulCommandBase
from src.core.interfaces.state_provider_interface import ISecureStateAccess, ISecureStateModification

class MyStatefulCommand(StatefulCommandBase, BaseCommand):
    def __init__(
        self,
        state_reader: ISecureStateAccess,
        state_modifier: ISecureStateModification | None = None,
    ):
        """Initialize with required state services."""
        StatefulCommandBase.__init__(self, state_reader, state_modifier)

    @property
    def name(self) -> str:
        return "my-stateful-command"

    @property
    def format(self) -> str:
        return "my-stateful-command(param=value)"

    @property
    def description(self) -> str:
        return "My stateful command description"

    @property
    def examples(self) -> list[str]:
        return ["!/my-stateful-command(param=value)"]

    async def execute(self, args: Mapping[str, Any], session: Session, context: Any = None) -> CommandResult:
        # Validate that this command was created through proper DI
        self._validate_di_usage()
        
        # Command implementation using state_reader and state_modifier
        return CommandResult(
            name=self.name,
            success=True,
            message="Command executed successfully",
        )
```

## Testing Commands

### Unit Tests

For unit tests, you can create mock dependencies and instantiate commands directly:

```python
from unittest.mock import Mock
from src.core.domain.commands.my_command import MyStatefulCommand
from src.core.interfaces.state_provider_interface import ISecureStateAccess, ISecureStateModification

def test_my_command():
    # Create mock dependencies
    mock_state_reader = Mock(spec=ISecureStateAccess)
    mock_state_modifier = Mock(spec=ISecureStateModification)
    
    # Create command with mock dependencies
    command = MyStatefulCommand(mock_state_reader, mock_state_modifier)
    
    # Test command
    # ...
```

### Integration Tests

For integration tests, use the `setup_test_command_registry()` helper in `tests/conftest.py`:

```python
from tests.conftest import setup_test_command_registry

def test_my_command_integration():
    # Set up the command registry with mock dependencies
    registry = setup_test_command_registry()
    
    # Get the command from the registry
    command = registry.get("my-stateful-command")
    
    # Test command
    # ...
```

## Conclusion

The DI-based command architecture ensures that commands are properly instantiated and have access to the dependencies they need. It also prevents direct instantiation of commands that require dependencies, ensuring that the command system is consistently using DI throughout the codebase.

By following this architecture, you can create new commands that are properly integrated with the DI system and have access to the dependencies they need.