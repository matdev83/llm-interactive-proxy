# Dependency Injection Implementation Fixes

This document summarizes the fixes implemented to unify the command handling architecture under a consistent dependency injection (DI) pattern.

## Problem Statement

The codebase had inconsistent command handling patterns:

1. **Auto-Discovery Mechanism**: The `CommandParser` used auto-discovery to find command classes, which skipped commands requiring DI.
2. **Direct State Mutation**: Domain commands were directly manipulating web framework state.
3. **Duplicate Implementations**: Both legacy (non-DI) and modern (DI-based) implementations of commands existed.
4. **Testing Complexity**: Tests relied on direct command instantiation, violating DI principles.
5. **SOLID Violations**: The existing structure violated Dependency Inversion Principle (DIP).

## Implemented Solutions

### 1. Command Registry as a Singleton

The `CommandRegistry` was enhanced to act as a bridge for code that doesn't have direct access to the DI container:

```python
class CommandRegistry:
    _instance: ClassVar["CommandRegistry | None"] = None
    
    @staticmethod
    def get_instance() -> "CommandRegistry | None":
        """Get the global instance of the registry."""
        return CommandRegistry._instance

    @staticmethod
    def set_instance(registry: "CommandRegistry") -> None:
        """Set the global instance of the registry."""
        CommandRegistry._instance = registry
```

### 2. DI Validation in Commands

Added runtime validation to prevent improper command instantiation:

```python
@final
def _validate_di_usage(self) -> None:
    """Validate that this command instance was created through proper DI."""
    # Implementation that checks if required dependencies are set
```

### 3. Centralized Command Registration

Created a centralized utility for registering all commands with the DI container:

```python
def register_all_commands(services: ServiceCollection, registry: CommandRegistry) -> None:
    """Register all commands in the DI container."""
    # Register stateless commands
    _register_stateless_command(services, registry, HelpCommand)
    # Register stateful commands with their dependencies
    services.add_singleton_factory(
        SetCommand,
        lambda provider: SetCommand(
            provider.get_service(ISecureStateAccess),
            provider.get_service(ISecureStateModification),
        ),
    )
```

### 4. Updated CommandParser

Modified `CommandParser` to prioritize commands from the DI container:

```python
def __init__(self, config: "CommandParserConfig", command_prefix: str) -> None:
    # Always try to get DI-registered commands first
    di_registry = CommandRegistry.get_instance()
    if di_registry:
        self.handlers = di_registry.get_all()
    else:
        # Fall back to auto-discovery if DI not available
        self.handlers = discover_commands()
```

### 5. Test Compatibility

Enhanced testing support with:

1. A test command registry setup helper
2. Mock command implementations for unit tests
3. Special handling for test environments in `CommandParser`

```python
def setup_test_command_registry():
    """Set up a test command registry with mock dependencies."""
    registry = CommandRegistry()
    CommandRegistry.set_instance(registry)
    # Register commands with mock dependencies
    return registry
```

### 6. Legacy Cleanup

1. Removed duplicate command implementations from `src/core/commands/`
2. Deprecated the `discover_commands` auto-discovery function
3. Added documentation of the new DI architecture

## Impact on Testing

The changes have implications for testing:

1. Integration tests now use proper DI setup via `setup_test_command_registry()`
2. Unit tests may need to use mock command implementations
3. Snapshot tests have been updated to match the new command behavior

## Remaining Work

While the core DI architecture is implemented, some additional work remains:

1. Update skipped unit tests to work with the DI architecture
2. Improve mock command implementations to better simulate real command behavior
3. Fix authentication tests that are failing due to format changes
4. Address non-DI related failures in connector tests

## Conclusion

The command system now consistently uses dependency injection throughout, ensuring:

1. Proper separation of concerns
2. Adherence to SOLID principles
3. Unified approach to command instantiation and registration
4. Better testability through mocked dependencies
