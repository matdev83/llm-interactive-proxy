import importlib
import inspect
import pkgutil

from src.core.domain.commands.base_command import BaseCommand


def discover_commands(
    package_path: str = "src.core.domain.commands",
) -> dict[str, BaseCommand]:
    """
    Auto-discovers and instantiates all command classes in a given package.

    This function scans the specified package for modules, imports them, and searches
    for classes that are subclasses of BaseCommand. It instantiates each found
    command and returns a dictionary mapping the command's registered name to its
    instance.

    Args:
        package_path: The dotted path to the package containing command modules
                      (e.g., 'src.core.domain.commands').

    Returns:
        A dictionary where keys are the command names (e.g., 'set', 'help')
        and values are the corresponding command instances.
    """
    handlers: dict[str, BaseCommand] = {}

    # Find the actual file system path for the package
    try:
        package = importlib.import_module(package_path)
    except ImportError:
        # Handle cases where the top-level package might not be a module itself
        # and just a namespace.
        return handlers

    # pkgutil.iter_modules requires a list of paths
    module_path = getattr(package, "__path__", [])
    if not module_path:
        return handlers

    for _, module_name, _ in pkgutil.iter_modules(module_path, package.__name__ + "."):
        try:
            module = importlib.import_module(module_name)
            for _, obj in inspect.getmembers(module, inspect.isclass):
                # Check if the class is a subclass of BaseCommand and not BaseCommand itself
                if issubclass(obj, BaseCommand) and obj is not BaseCommand:
                    # Instantiate the command
                    command_instance = obj()
                    # The command name should be an attribute on the instance
                    if hasattr(command_instance, "name") and command_instance.name:
                        if command_instance.name in handlers:
                            # Log a warning or raise an error for duplicate command names
                            pass
                        handlers[command_instance.name] = command_instance
        except Exception:
            # Log errors for debugging, e.g., print(f"Could not process {module_name}: {e}")
            pass

    return handlers
