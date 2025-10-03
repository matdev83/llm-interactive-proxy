"""
A decorator-based command registry.
"""

from collections.abc import Callable

from src.core.commands.handler import ICommandHandler

_registry: dict[str, type[ICommandHandler]] = {}


def command(name: str) -> Callable[[type[ICommandHandler]], type[ICommandHandler]]:
    """
    A decorator to register a command handler.

    Args:
        name: The name of the command to register.

    Returns:
        A decorator that registers the command handler.
    """

    def decorator(cls: type[ICommandHandler]) -> type[ICommandHandler]:
        if name in _registry:
            raise ValueError(f"Command '{name}' is already registered.")
        _registry[name] = cls
        return cls

    return decorator


def get_command_handler(name: str) -> type[ICommandHandler] | None:
    """
    Gets the command handler for a given command name.

    Args:
        name: The name of the command.

    Returns:
        The command handler class, or None if not found.
    """
    return _registry.get(name)


def get_all_commands() -> dict[str, type[ICommandHandler]]:
    """
    Gets all registered command handlers.

    Returns:
        A dictionary of command names to their handler classes.
    """
    return _registry.copy()


def clear_registry() -> None:
    """
    Clears the command registry.
    """
    _registry.clear()
