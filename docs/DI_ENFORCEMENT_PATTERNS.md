# Dependency Injection Enforcement Patterns

This document describes the architectural safeguards implemented to enforce proper dependency injection (DI) usage in the codebase.

## Overview

To ensure consistent dependency injection usage and prevent bypassing the DI container, several enforcement patterns have been implemented:

1. **Runtime DI Validation**: Commands validate at runtime that they were properly instantiated through DI
2. **Centralized Registration**: A single source of truth for command registration

## Runtime DI Validation

The `BaseCommand` class includes a `_validate_di_usage()` method that commands call in their `execute()` method to verify they were properly instantiated through DI:

```python
@final
def _validate_di_usage(self) -> None:
    """
    Validate that this command instance was created through proper DI.
    
    This method should be called by commands that require dependency injection
    to ensure they weren't instantiated directly without proper dependencies.
    
    Raises:
        RuntimeError: If the command was instantiated without proper DI
    """
    # Check if this command requires DI by examining its constructor
    import inspect
    
    # Get the constructor's class
    constructor_class = self.__class__
    
    # Skip validation for classes that don't need DI
    if (constructor_class.__init__ is BaseCommand.__init__ or 
        constructor_class.__init__.__qualname__.startswith(constructor_class.__name__)):
        return
    
    # Examine constructor signature for required parameters
    init_signature = inspect.signature(constructor_class.__init__)
    required_params = [
        name for name, param in init_signature.parameters.items()
        if name != "self" and param.default is inspect.Parameter.empty
    ]
    
    # Verify required dependencies are set
    if required_params:
        missing_deps = []
        for param_name in required_params:
            attr_name = f"_{param_name}"
            if not hasattr(self, attr_name) or getattr(self, attr_name) is None:
                missing_deps.append(param_name)
        
        if missing_deps:
            raise RuntimeError(
                f"Command {self.__class__.__name__} requires dependency injection "
                f"but was instantiated without required dependencies: {missing_deps}. "
                f"Use dependency injection container to create this command instead "
                f"of direct instantiation."
            )
```

## CommandRegistry Validation

The `CommandRegistry` enforces DI validation when registering commands:

```python
def register(self, command: BaseCommand) -> None:
    """Register a command handler.
    
    Args:
        command: The command handler to register
    """
    # Validate that the command was created through proper DI
    command._validate_di_usage()
    
    self._commands[command.name] = command
    logger.info(f"Registered command: {command.name}")
```

## Centralized Registration

A centralized command registration utility ensures all commands are registered in a consistent manner:

```python
def register_all_commands(
    services: ServiceCollection,
    registry: CommandRegistry,
) -> None:
    """Register all commands in the DI container.
    
    This function registers all known commands in the DI container, making them
    available for injection. It also registers them in the command registry for
    lookup by name.
    
    Args:
        services: The service collection to register commands with
        registry: The command registry to register commands with
    """
    # Register stateless commands (no dependencies)
    _register_stateless_command(services, registry, HelpCommand)
    _register_stateless_command(services, registry, HelloCommand)
    # ... other stateless commands ...
    
    # Register stateful commands (require dependencies)
    services.add_singleton_factory(
        SetCommand,
        lambda provider: SetCommand(
            provider.get_service(ISecureStateAccess),
            provider.get_service(ISecureStateModification),
        ),
    )
    # ... other stateful commands ...
    
    # Register all commands in the registry for lookup by name
    _register_all_commands_in_registry(services, registry)
```

## Testing Support

For testing environments, special accommodations are made:

1. The `_validate_di_usage()` method in `BaseCommand` automatically skips validation for stateless commands
2. The `setup_test_command_registry()` helper in `conftest.py` provides a properly configured registry for tests
3. Mock command implementations are provided for unit tests that don't set up the full DI container

## Guidelines for Future Development

When developing new commands or modifying existing ones:

1. **Register all commands in the DI container**
   - Add new commands to `src/core/services/command_registration.py`
   - Stateless commands: Use `_register_stateless_command(services, registry, MyCommand)`
   - Stateful commands: Add a singleton factory with explicit dependencies

2. **Implement proper dependency injection**
   - Define clear interfaces for dependencies in `src/core/interfaces/`
   - Accept dependencies through constructors, not through service locators
   - Store dependencies as protected attributes (e.g., `self._state_reader`)

3. **Use the `BaseCommand` validation**
   - Call `self._validate_di_usage()` in your command's `execute` method
   - This ensures the command was properly instantiated through DI

4. **Follow the test patterns in `tests/conftest.py`**
   - Use `setup_test_command_registry()` for integration tests
   - Provide mock dependencies for stateful commands

## Benefits

These enforcement patterns provide several benefits:

1. **Consistency**: All commands follow the same DI pattern
2. **Maintainability**: Dependencies are explicit and injected through constructors
3. **Testability**: Commands can be easily tested with mock dependencies
4. **Error Prevention**: Runtime checks prevent accidental direct instantiation
5. **Discoverability**: Centralized registration makes it easy to find all commands

## Conclusion

By implementing these architectural safeguards, we've ensured that the command system consistently uses dependency injection throughout the codebase. This improves maintainability, testability, and adherence to SOLID principles, particularly the Dependency Inversion Principle.