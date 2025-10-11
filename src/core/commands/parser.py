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

    def parse(
        self, content: str, command_prefix: str | None = None
    ) -> tuple[Command, str] | None:
        """
        Parses a command from the given content.

        Args:
            content: The content to parse.

        Returns:
            A tuple containing the Command object and the matched string, or None.
        """
        prefix_value: str | None = command_prefix if command_prefix else self.command_prefix
        if not isinstance(prefix_value, str) or not prefix_value:
            return None

        prefix = prefix_value
        search_index = 0
        while True:
            start = content.find(prefix, search_index)
            if start == -1:
                return None

            cursor = start + len(prefix)
            if cursor >= len(content):
                return None

            name_chars: list[str] = []
            while cursor < len(content) and (
                content[cursor].isalnum() or content[cursor] in "-_"
            ):
                name_chars.append(content[cursor])
                cursor += 1

            if not name_chars:
                search_index = start + len(prefix)
                continue

            name = "".join(name_chars)

            name_end = cursor
            whitespace_cursor = cursor
            while (
                whitespace_cursor < len(content)
                and content[whitespace_cursor].isspace()
            ):
                whitespace_cursor += 1

            matched_end = name_end
            args: dict[str, Any] = {}
            if whitespace_cursor < len(content) and content[whitespace_cursor] == "(":
                cursor = whitespace_cursor + 1
                args_start = cursor
                depth = 1
                quote_char: str | None = None
                escape_next = False

                while cursor < len(content):
                    char = content[cursor]
                    if escape_next:
                        escape_next = False
                    elif quote_char is not None:
                        if char == "\\":
                            escape_next = True
                        elif char == quote_char:
                            quote_char = None
                    else:
                        if char in ('"', "'"):
                            quote_char = char
                        elif char == "(":
                            depth += 1
                        elif char == ")":
                            depth -= 1
                            if depth == 0:
                                break
                    cursor += 1

                if depth != 0:
                    # Unbalanced parentheses - skip this occurrence and keep searching
                    search_index = start + len(prefix)
                    continue

                args_str = content[args_start:cursor]
                matched_end = cursor + 1
                args = self._parse_args(args_str)
            else:
                cursor = name_end
            matched_text = content[start:matched_end]
            return Command(name=name, args=args), matched_text

    def _parse_args(self, args_str: str) -> dict[str, Any]:
        """Parse the arguments string into a dictionary."""

        def _split_args(raw: str) -> list[str]:
            parts: list[str] = []
            current: list[str] = []
            depth = 0
            quote_char: str | None = None
            escape_next = False

            opening = "({["
            closing = ")}]"
            matching = {")": "(", "}": "{", "]": "["}

            for char in raw:
                if escape_next:
                    current.append(char)
                    escape_next = False
                    continue

                if quote_char is not None:
                    if char == "\\":
                        current.append(char)
                        escape_next = True
                        continue
                    current.append(char)
                    if char == quote_char:
                        quote_char = None
                    continue

                if char in ('"', "'"):
                    quote_char = char
                    current.append(char)
                    continue

                if char in opening:
                    depth += 1
                    current.append(char)
                    continue

                if char in closing:
                    if depth > 0 and matching.get(char) is not None:
                        depth -= 1
                    current.append(char)
                    continue

                if char == "," and depth == 0:
                    part = "".join(current).strip()
                    if part:
                        parts.append(part)
                    current = []
                    continue

                if char == "\\":
                    current.append(char)
                    escape_next = True
                    continue

                current.append(char)

            final_part = "".join(current).strip()
            if final_part:
                parts.append(final_part)
            return parts

        args: dict[str, Any] = {}
        for part in _split_args(args_str):
            if "=" in part:
                key, value = part.split("=", 1)
                args[key.strip()] = value.strip()
            else:
                # Support key-only arguments like unset(temperature)
                args[part.strip()] = ""
        return args
