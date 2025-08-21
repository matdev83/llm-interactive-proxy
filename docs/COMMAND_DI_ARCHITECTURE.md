# Command DI Architecture

## Overview

This document describes the Dependency Injection (DI) architecture for commands in the LLM Interactive Proxy. All commands now follow a standardized DI-based pattern, ensuring proper separation of concerns and adherence to SOLID principles.

## Command Registration

Commands are registered in the DI container and the command registry during application startup. The `CommandStage` handles this registration process, using the centralized `register_all_commands` utility function.

### Registration Process

1. The `CommandStage` initializes services during application startup
2. It creates a new `CommandRegistry` instance and sets it as the global instance
3. It registers the command registry and command service in the DI container
4. It calls the `register_all_commands` utility to register all commands

### Command Types

Commands are divided into two types based on their dependency requirements:

1. **Stateless Commands**: Commands that don't require any dependencies and can be instantiated directly.
2. **Stateful Commands**: Commands that require dependencies, such as state access services, which are injected through their constructors.

## Command Implementation

### Base Command Interface

All commands inherit from the `BaseCommand` abstract base class, which defines the core command interface:

```python
class BaseCommand(ABC):
    @abstractproperty
    def name(self) -> str:
        """The command name, used to invoke the command."""
        pass

    @abstractproperty
    def description(self) -> str:
        """A description of what the command does."""
        pass

    @abstractproperty
    def format(self) -> str:
        """The command format, showing how to use it."""
        pass

    @abstractmethod
    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Execute the command."""
        pass
```

### Dependency Injection Validation

Each command's constructor is validated to ensure it has been properly instantiated through DI. The `_validate_di_usage()` method checks that all required dependencies are set.

### Stateless Commands

Stateless commands have a simple implementation with no constructor parameters:

```python
class HelloCommand(BaseCommand):
    @property
    def name(self) -> str:
        return "hello"

    @property
    def description(self) -> str:
        return "A simple hello world command"

    @property
    def format(self) -> str:
        return "hello"

    async def execute(self, args, session, context=None):
        return CommandResult(
            success=True,
            message="Hello, world!",
            name=self.name
        )
```

### Stateful Commands

Stateful commands declare their dependencies in their constructor:

```python
class SetCommand(BaseCommand):
    def __init__(
        self, state_reader: ISecureStateAccess, state_modifier: ISecureStateModification
    ):
        self._state_reader = state_reader
        self._state_modifier = state_modifier

    @property
    def name(self) -> str:
        return "set"

    @property
    def description(self) -> str:
        return "Set session parameters"

    @property
    def format(self) -> str:
        return "set(param=value)"

    async def execute(self, args, session, context=None):
        # Validate that this command was created through proper DI
        self._validate_di_usage()
        
        # Implementation using injected dependencies
        # ...
```

## Command Discovery and Execution

### Command Registry

The `CommandRegistry` serves as a central repository for all registered commands. It provides methods to:

1. Register a command: `registry.register(command)`
2. Get a command by name: `registry.get("command-name")`
3. Get all registered commands: `registry.get_all()`

### CommandParser Integration

The `CommandParser` uses the global `CommandRegistry` instance to get all available commands:

```python
# Get commands from the DI registry
registry = CommandRegistry.get_instance()
if registry:
    self.handlers = registry.get_all()
else:
    # Fall back to auto-discovery (deprecated)
    self.handlers = discover_commands()
```

### Auto-Discovery (Deprecated)

The legacy `discover_commands()` function is now deprecated and will be removed in a future version. It cannot discover commands that require DI, and its use is discouraged.

## Testing Commands

For testing, a `setup_test_command_registry()` utility function is provided to create a properly configured command registry with all commands registered:

```python
def test_my_command():
    # Setup the registry with all commands
    setup_test_command_registry()
    
    # Now CommandParser will use the registry we just set up
    parser = CommandParser(config, prefix="!/")
    
    # Test the command
    # ...
```

## Best Practices

1. **All commands should use DI**: Even if a command doesn't have dependencies now, implement it following the DI pattern for consistency.
2. **Register commands in the central utility**: Add new commands to the `register_all_commands` function in `src/core/services/command_registration.py`.
3. **Use interface dependencies**: Depend on interfaces (like `ISecureStateAccess`) rather than concrete implementations.
4. **Validate DI usage**: Call `self._validate_di_usage()` in your `execute()` method to ensure proper instantiation.
5. **Testing**: Use the `setup_test_command_registry()` helper to ensure tests have access to all commands.
