"""
Parses commands from message content.
"""

import re
from typing import Any

from src.core.commands.command import Command


class CommandParser:
    """
    A service that parses commands from message content.
    """

    def __init__(self, command_prefix: str = "!/"):
        """
        Initializes the command parser.

        Args:
            command_prefix: The prefix used to identify commands.
        """
        self.command_prefix = command_prefix
        self.pattern = self._compile_pattern()
        # Ensure command handlers are imported so their @command decorators register them
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

    def _compile_pattern(self) -> re.Pattern:
        """
        Compiles the regex pattern for command parsing.
        """
        escaped_prefix = re.escape(self.command_prefix)
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
