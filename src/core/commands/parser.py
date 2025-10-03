"""
Parses commands from message content.
"""

import re
from typing import Any

from src.core.commands.command import Command


class CommandParser:
    """Parses command invocations from message content."""

    def __init__(self, command_prefix: str = "!/"):
        """Initialize the parser with the desired command prefix."""
        self._command_prefix: str = ""
        self.pattern: re.Pattern
        self.command_prefix = command_prefix
        self._import_command_handlers()

    @property
    def command_prefix(self) -> str:
        """Return the current command prefix."""
        return self._command_prefix

    @command_prefix.setter
    def command_prefix(self, value: str) -> None:
        """Update the command prefix and refresh the parsing pattern."""
        if not isinstance(value, str):
            raise TypeError("Command prefix must be a string.")
        if value == "":
            raise ValueError("Command prefix must not be empty.")

        self._command_prefix = value
        self.pattern = self._compile_pattern(value)

    def set_command_prefix(self, command_prefix: str) -> None:
        """Public helper to update the command prefix via method call."""
        self.command_prefix = command_prefix

    def _import_command_handlers(self) -> None:
        """Eagerly import handlers so decorator registration runs under DI."""
        try:
            import importlib
            import pkgutil

            package_name = "src.core.commands.handlers"
            package = importlib.import_module(package_name)
            for m in pkgutil.iter_modules(package.__path__):  # type: ignore[attr-defined]
                importlib.import_module(f"{package_name}.{m.name}")
        except Exception:
            # Parsing still works even if handlers fail to import; execution will no-op
            pass

    def _compile_pattern(self, prefix: str | None = None) -> re.Pattern:
        """Compile the regex pattern for command parsing using the given prefix."""
        escaped_prefix = re.escape(
            prefix if prefix is not None else self.command_prefix
        )
        return re.compile(rf"{escaped_prefix}(?P<name>[\w-]+)(?:\((?P<args>[^)]*)\))?")

    def parse(self, content: str) -> tuple[Command, str] | None:
        """
        Parses a command from the given content.

        Args:
            content: The content to parse.

        Returns:
            A tuple containing the Command object and the matched string, or None.
        """
        match = self.pattern.search(content)
        if not match:
            return None

        name = match.group("name")
        args_str = match.group("args")
        args = self._parse_args(args_str) if args_str else {}

        return Command(name=name, args=args), match.group(0)

    def _parse_args(self, args_str: str) -> dict[str, Any]:
        """
        Parses the arguments string into a dictionary.
        """
        # This is a simplified parser. A more robust implementation could
        # handle quoted strings, different data types, etc.
        args = {}
        for part in args_str.split(","):
            part = part.strip()
            if not part:
                continue
            if "=" in part:
                key, value = part.split("=", 1)
                args[key.strip()] = value.strip()
            else:
                # Support key-only arguments like unset(temperature)
                args[part.strip()] = ""
        return args
