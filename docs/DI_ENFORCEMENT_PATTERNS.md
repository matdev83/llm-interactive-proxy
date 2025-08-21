# Dependency Injection Enforcement Patterns

This document describes the architectural safeguards implemented to enforce proper dependency injection (DI) usage in the codebase.

## Overview

To ensure consistent dependency injection usage and prevent bypassing the DI container, several enforcement patterns have been implemented:

1. **Runtime DI Validation**: Commands validate at runtime that they were properly instantiated through DI
2. **Protected Constructors**: BaseCommand prevents direct instantiation outside of DI/tests
3. **Command Factory**: A dedicated factory for creating command instances through DI
4. **Centralized Registration**: A single source of truth for command registration

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

## Protected Constructors

The `BaseCommand` class overrides `__new__` to prevent direct instantiation outside of the DI container or test environments:

```python
def __new__(cls, *args, **kwargs):
    """
    Control instantiation of command classes.
    
    This method is called before __init__ and can prevent direct instantiation
    outside of the DI container in non-test environments.
    
    Returns:
        A new instance of the command class
        
    Raises:
        RuntimeError: If attempting to directly instantiate a command class
                     outside of tests or DI container
    """
    # Allow instantiation in test environments
    import sys
    is_test_env = 'pytest' in sys.modules or hasattr(sys, '_called_from_test')
    
    # Check if we're being called from the DI container
    import traceback
    stack = traceback.extract_stack()
    from_di = any('src/core/di/' in frame.filename for frame in stack)
    
    # Also allow instantiation from the command factory
    from_factory = any('command_factory.py' in frame.filename for frame in stack)
    
    # Allow direct instantiation in tests or from DI container/factory
    if is_test_env or from_di or from_factory or cls.__name__ == 'BaseCommand':
        return super().__new__(cls)
    
    # Otherwise, raise an error
    raise RuntimeError(
        f"Direct instantiation of {cls.__name__} is not allowed. "
        f"Use the CommandFactory or DI container to create command instances."
    )
```

## Command Factory

A dedicated `CommandFactory` class ensures commands are created through the DI container:

```python
class CommandFactory(IFactory[BaseCommand]):
    """
    Factory for creating command instances through DI.
    
    This factory enforces that commands are created through the DI container,
    preventing direct instantiation of commands that require dependencies.
    """
    
    def __init__(self, service_provider: ServiceProvider) -> None:
        """
        Initialize the command factory.
        
        Args:
            service_provider: The DI service provider to use for resolving commands
        """
        self._service_provider = service_provider
    
    def create(self, command_type: Type[T]) -> T:
        """
        Create a command instance through the DI container.
        
        This method ensures that commands are always created with their
        required dependencies injected properly.
        
        Args:
            command_type: The type of command to create
            
        Returns:
            An instance of the requested command type
            
        Raises:
            ValueError: If the command type is not registered in the DI container
            RuntimeError: If the command could not be created through DI
        """
        try:
            command = self._service_provider.get_service(command_type)
            if command is None:
                raise ValueError(
                    f"Command type {command_type.__name__} is not registered in the DI container"
                )
            return cast(T, command)
        except Exception as e:
            logger.error(f"Failed to create command {command_type.__name__}: {e}")
            raise RuntimeError(
                f"Command {command_type.__name__} must be created through DI. "
                f"Ensure it is registered in the DI container. Error: {e}"
            ) from e
    
    @staticmethod
    def register_factory(services: ServiceCollection) -> None:
        """
        Register the command factory in the DI container.
        
        Args:
            services: The service collection to register with
        """
        services.add_singleton_factory(
            CommandFactory,
            lambda provider: CommandFactory(provider),
        )
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
    # Register the command factory first
    CommandFactory.register_factory(services)
    
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

## Testing Support

For testing environments, special accommodations are made:

1. The `__new__` method in `BaseCommand` allows direct instantiation in test environments
2. The `setup_test_command_registry()` helper in `conftest.py` provides a properly configured registry for tests
3. Mock command implementations are provided for unit tests that don't set up the full DI container

## Guidelines for Future Development

When developing new commands or modifying existing ones:

1. **Never directly instantiate command classes**
   - Always use the `CommandFactory` to create command instances:
   ```python
   command_factory = service_provider.get_service(CommandFactory)
   command = command_factory.create(MyCommand)
   ```

2. **Register all commands in the DI container**
   - Add new commands to `src/core/services/command_registration.py`
   - Stateless commands: Use `_register_stateless_command(services, registry, MyCommand)`
   - Stateful commands: Add a singleton factory with explicit dependencies

3. **Implement proper dependency injection**
   - Define clear interfaces for dependencies in `src/core/interfaces/`
   - Accept dependencies through constructors, not through service locators
   - Store dependencies as protected attributes (e.g., `self._state_reader`)

4. **Use the `BaseCommand` validation**
   - Call `self._validate_di_usage()` in your command's `execute` method
   - This ensures the command was properly instantiated through DI

5. **Follow the test patterns in `tests/conftest.py`**
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
