# Testing with Dependency Injection Architecture

This guide explains how to write and update tests to work with the new dependency injection (DI) architecture for commands in the proxy.

## Overview of Changes

The command system has been refactored to use proper dependency injection:

1. Commands requiring state access are now created via DI
2. The `CommandParser` now gets commands from the DI container's `CommandRegistry`
3. Runtime validation is enforced to prevent direct instantiation of commands that require dependencies
4. Legacy command implementations have been removed

## Testing Strategies

### Integration Tests

For integration tests, use the `setup_test_command_registry()` helper in `conftest.py`:

```python
from tests.conftest import setup_test_command_registry

def test_my_command_functionality():
    # Set up the DI command registry with mock dependencies
    registry = setup_test_command_registry()
    
    # Get the command from the registry
    command = registry.get("set")
    
    # Test the command
    # ...
```

This helper:
- Creates a new `CommandRegistry` instance
- Sets it as the global instance
- Creates mock dependencies for stateful commands
- Registers all commands with the registry
- Returns the registry for use in tests

### Unit Tests

For unit tests, you can create mock dependencies and instantiate commands directly:

```python
from unittest.mock import Mock
from src.core.domain.commands.set_command import SetCommand
from src.core.interfaces.state_provider_interface import ISecureStateAccess, ISecureStateModification

def test_set_command():
    # Create mock dependencies
    mock_state_reader = Mock(spec=ISecureStateAccess)
    mock_state_modifier = Mock(spec=ISecureStateModification)
    
    # Create command with mock dependencies
    command = SetCommand(mock_state_reader, mock_state_modifier)
    
    # Test the command
    # ...
```

For tests that need to use `CommandParser` but don't want to set up the full DI container, you can use the mock commands in `tests/unit/mock_commands.py`:

```python
from src.command_parser import CommandParser, CommandParserConfig
from tests.unit.mock_commands import get_mock_commands

def test_command_parser():
    # Create a command parser with mock commands
    handlers = get_mock_commands()
    config = CommandParserConfig(handlers=handlers, preserve_unknown=True)
    parser = CommandParser(config, "!/")
    
    # Test the parser
    # ...
```

### Command Processor Tests

For tests that use the `CommandProcessor`, you need to ensure that the commands are properly registered in the `CommandRegistry`. You can use the `setup_test_command_registry()` helper:

```python
from tests.conftest import setup_test_command_registry
from src.core.domain.command_processor import CommandProcessor

def test_command_processor():
    # Set up the command registry
    registry = setup_test_command_registry()
    
    # Create a command processor that uses the registry
    processor = CommandProcessor(registry)
    
    # Test the processor
    # ...
```

## Handling Skipped Tests

Many tests have been skipped because they were testing legacy command implementations or were not compatible with the new DI architecture. To update these tests:

1. Remove the `@pytest.mark.skip` decorator
2. Update the test to use the DI-based commands
3. Run the test to verify it passes

Example of updating a skipped test:

```python
# Before
@pytest.mark.skip("Skipping until command handling in tests is fixed")
def test_set_command():
    # Old test code using legacy commands
    # ...

# After
def test_set_command():
    # Set up the command registry
    registry = setup_test_command_registry()
    
    # Get the command from the registry
    command = registry.get("set")
    
    # Test the command
    # ...
```

## Testing Stateful Commands

Stateful commands require dependencies to be injected. When testing these commands:

1. Create mock dependencies
2. Instantiate the command with the mock dependencies
3. Configure the mock dependencies to return the expected values
4. Test the command's behavior

Example:

```python
def test_set_command_with_dependencies():
    # Create mock dependencies
    mock_state_reader = Mock(spec=ISecureStateAccess)
    mock_state_modifier = Mock(spec=ISecureStateModification)
    
    # Configure the mocks
    mock_state_reader.get_backend_config.return_value = {"backend": "test"}
    
    # Create command with mock dependencies
    command = SetCommand(mock_state_reader, mock_state_modifier)
    
    # Create a mock session
    mock_session = Mock()
    mock_session.state = Mock()
    
    # Execute the command
    result = await command.execute({"param": "value"}, mock_session)
    
    # Verify the result
    assert result.success is True
    assert result.message == "Parameter set successfully"
    
    # Verify the mock was called
    mock_state_modifier.set_parameter.assert_called_once_with("param", "value")
```

## Testing CommandParser with DI

When testing the `CommandParser`, you need to ensure that the `CommandRegistry` is properly set up:

```python
def test_command_parser_with_di():
    # Set up the command registry
    registry = setup_test_command_registry()
    
    # Create a command parser config
    config = CommandParserConfig(preserve_unknown=True)
    
    # Create a command parser
    parser = CommandParser(config, "!/")
    
    # Verify that the parser is using the registry's commands
    assert "set" in parser.handlers
    assert "unset" in parser.handlers
    
    # Test the parser
    # ...
```

## Testing Snapshot Tests

For snapshot tests that depend on command output, you may need to update the snapshots to match the new command behavior:

```python
def test_help_command_snapshot(snapshot):
    # Set up the command registry
    registry = setup_test_command_registry()
    
    # Get the help command
    help_command = registry.get("help")
    
    # Execute the command
    mock_session = Mock()
    result = await help_command.execute({}, mock_session)
    
    # Verify the result matches the snapshot
    assert result.message == snapshot
```

To update snapshots, run pytest with the `UPDATE_SNAPSHOTS=true` environment variable:

```bash
UPDATE_SNAPSHOTS=true ./.venv/Scripts/python.exe -m pytest tests/integration/commands/test_integration_help_command.py
```

## Conclusion

The new DI architecture for commands makes testing more consistent and reliable. By following the strategies outlined in this guide, you can write tests that work with the new architecture and ensure that your commands are properly instantiated and have access to the dependencies they need.