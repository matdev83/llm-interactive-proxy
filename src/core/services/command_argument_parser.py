from __future__ import annotations

import shlex

from src.core.interfaces.command_argument_parser_interface import (
    ICommandArgumentParser,
)


class CommandArgumentParser(ICommandArgumentParser):
    """Robust parser for command argument strings like "--a=1 --b=two".

    - Supports --key=value tokens (preferred)
    - Strips leading dashes from keys
    - Coerces simple integers when unambiguous
    - Ignores malformed tokens gracefully
    """

    def parse(self, args_str: str | None) -> dict[str, object]:
        if not args_str:
            return {}

        result: dict[str, object] = {}

        try:
            tokens = shlex.split(args_str)
        except Exception:
            tokens = args_str.split()

        for token in tokens:
            if not token.startswith("-"):
                # Skip bare tokens to avoid mis-association
                continue

            # Only handle --key=value form
            if "=" not in token:
                continue

            key_part, value_part = token.split("=", 1)
            key = key_part.lstrip("-")
            value: object = value_part

            # Simple integer coercion
            if value_part.isdigit():
                try:
                    value = int(value_part)
                except ValueError:
                    value = value_part

            result[key] = value

        return result
