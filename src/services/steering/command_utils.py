"""Shared command parsing utilities for steering policies."""

from __future__ import annotations

import json
from typing import Any


def extract_command_from_arguments(arguments: Any) -> str | None:
    """Extract shell command string from tool arguments.

    Supports various shapes:
    - Raw string
    - JSON string containing command
    - Dict with command/cmd/input keys
    - List of command parts

    Args:
        arguments: Tool call arguments in any format

    Returns:
        Extracted command string, or None if not found
    """
    if arguments is None:
        return None

    # Handle raw string
    if isinstance(arguments, str):
        # Try parsing as JSON first
        try:
            parsed = json.loads(arguments)
        except (TypeError, ValueError):
            # Treat as raw command if not JSON
            return arguments.strip() if arguments.strip() else None
        arguments = parsed

    # Handle dictionary
    if isinstance(arguments, dict):
        # Check common command keys
        command = arguments.get("command") or arguments.get("cmd")
        if isinstance(command, str) and command.strip():
            return command.strip()
        if isinstance(command, list) and command:
            return " ".join(str(item) for item in command)

        # Check nested input/body/data keys
        for key in ("input", "body", "data"):
            inner = arguments.get(key)
            if isinstance(inner, str) and inner.strip():
                return inner.strip()
            if isinstance(inner, dict):
                sub = inner.get("command") or inner.get("cmd")
                if isinstance(sub, str) and sub.strip():
                    return sub.strip()
                if isinstance(sub, list) and sub:
                    return " ".join(str(item) for item in sub)

        # Check args list
        args_list = arguments.get("args")
        if isinstance(args_list, str):
            return args_list.strip() if args_list.strip() else None
        if isinstance(args_list, list) and args_list:
            return " ".join(str(item) for item in args_list)

        return None

    # Handle list (sequence of command parts)
    if isinstance(arguments, list) and arguments:
        return " ".join(str(item) for item in arguments)

    return None


def normalize_whitespace(command: str) -> str:
    """Collapse whitespace in command string.

    Args:
        command: Raw command string

    Returns:
        Command with normalized whitespace
    """
    return " ".join(command.strip().split())


__all__ = ["extract_command_from_arguments", "normalize_whitespace"]
