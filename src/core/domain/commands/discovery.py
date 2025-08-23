import importlib
import inspect
import pkgutil

from src.core.domain.commands.base_command import BaseCommand


def discover_commands(
    package_path: str = "src.core.domain.commands",
) -> dict[str, BaseCommand]:
    """
    Auto-discovers and instantiates all command classes in a given package.

    ⚠️ DEPRECATED: This function is deprecated and will be removed in a future version.
    Use dependency injection (DI) to register commands instead. Commands requiring
    DI will be skipped by this function.

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

    Note:
        Commands requiring dependency injection are skipped. Use DI container
        registration for those commands.
    """
    import warnings

    warnings.warn(
        "discover_commands() is deprecated. Use dependency injection to register commands instead.",
        DeprecationWarning,
        stacklevel=2,
    )

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
                    # Try to instantiate the command
                    command_instance = None
                    try:
                        # First try to instantiate without parameters (for backward compatibility)
                        command_instance = obj()
                    except TypeError as e:
                        if "missing" in str(e) and "argument" in str(e):
                            # This command requires dependency injection
                            # For now, we'll skip DI-required commands in discovery
                            # They should be registered manually in the DI container
                            continue
                        else:
                            # Re-raise unexpected TypeError
                            raise

                    if (
                        command_instance is not None
                        and hasattr(command_instance, "name")
                        and command_instance.name
                    ):
                        # The command name should be an attribute on the instance
                        if command_instance.name in handlers:
                            # Log a warning or raise an error for duplicate command names
                            pass
                        handlers[command_instance.name] = command_instance
        except Exception:
            # Log errors for debugging, e.g., print(f"Could not process {module_name}: {e}")
            pass

    # Additionally attempt to discover compatibility shims from the
    # `src.core.commands.handlers` package (legacy handler shims).
    try:
        extra_pkg = importlib.import_module("src.core.commands.handlers")
        extra_module_path = getattr(extra_pkg, "__path__", [])
        for _, module_name, _ in pkgutil.iter_modules(
            extra_module_path, extra_pkg.__name__ + "."
        ):
            try:
                module = importlib.import_module(module_name)
                for _, obj in inspect.getmembers(module, inspect.isclass):
                    # Accept either new-style BaseCommand implementations or
                    # legacy handler shims that expose `name` and `execute`.
                    try:
                        is_new_style = (
                            issubclass(obj, BaseCommand) and obj is not BaseCommand
                        )
                    except Exception:
                        is_new_style = False
                    if is_new_style:
                        try:
                            command_instance = obj()
                        except TypeError:
                            # Skip DI-required constructors
                            continue
                    else:
                        # For legacy handlers, accept any class that has `name` and `execute`
                        if hasattr(obj, "name") and callable(
                            getattr(obj, "execute", None)
                        ):
                            try:
                                command_instance = obj()
                            except TypeError:
                                continue
                        else:
                            continue

                    if (
                        command_instance is not None
                        and hasattr(command_instance, "name")
                        and command_instance.name
                    ):
                        if command_instance.name in handlers:
                            # Log a warning or raise an error for duplicate command names
                            pass
                        handlers[command_instance.name] = command_instance
            except Exception:
                # ignore errors importing/instantiating compatibility handlers
                pass
    except ImportError:
        # no compatibility handlers package available
        pass

    # Also attempt to discover legacy command classes in `src.core.commands`.
    try:
        legacy_pkg = importlib.import_module("src.core.commands")
        legacy_module_path = getattr(legacy_pkg, "__path__", [])
        for _, module_name, _ in pkgutil.iter_modules(
            legacy_module_path, legacy_pkg.__name__ + "."
        ):
            try:
                module = importlib.import_module(module_name)
                for _, obj in inspect.getmembers(module, inspect.isclass):
                    # Accept classes that either subclass BaseCommand or look like legacy handlers
                    try:
                        is_new_style = (
                            issubclass(obj, BaseCommand) and obj is not BaseCommand
                        )
                    except Exception:
                        is_new_style = False
                    if is_new_style:
                        try:
                            command_instance = obj()
                        except TypeError:
                            continue
                    else:
                        if hasattr(obj, "name") and callable(
                            getattr(obj, "execute", None)
                        ):
                            try:
                                command_instance = obj()
                            except TypeError:
                                continue
                        else:
                            continue

                    if (
                        command_instance is not None
                        and hasattr(command_instance, "name")
                        and command_instance.name
                    ):
                        if command_instance.name in handlers:
                            pass
                        handlers[command_instance.name] = command_instance
            except Exception:
                pass
    except ImportError:
        pass

    return handlers
