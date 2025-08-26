"""
Shared utilities for parsing command argument strings.

This module centralizes the parsing logic so both the legacy and the
DI-driven command paths behave consistently.
"""

from __future__ import annotations

import json
from typing import Any


def parse_command_arguments(args_str: str | None) -> dict[str, Any]:
    """Parse command arguments from a string.

    Rules:
    - If ``args_str`` is falsy, return an empty dict.
    - Try to parse JSON first. If it is a JSON object, return it as a dict.
      If it is valid JSON but not an object (e.g., string/number/bool), wrap
      it under the key ``"value"``.
    - Otherwise fall back to a simple comma-separated ``key=value`` format.
      Quoted values using single or double quotes are unwrapped.
      Flags without ``=`` are treated as boolean True.
    - If a token looks like a path or model identifier (contains ':' or '/'),
      and has no ``=``, store it under ``"element"``.
    """
    args: dict[str, Any] = {}
    if not args_str:
        return args

    # Try JSON first
    try:
        parsed = json.loads(args_str)
        if isinstance(parsed, dict):
            return parsed
        return {"value": parsed}
    except json.JSONDecodeError:
        pass

    # Fallback simple parser: key=value pairs or flags
    for raw in args_str.split(","):
        token = raw.strip()
        if not token:
            continue
        if "=" in token:
            key, value = token.split("=", 1)
            val = value.strip()
            if (val.startswith('"') and val.endswith('"')) or (
                val.startswith("'") and val.endswith("'")
            ):
                val = val[1:-1]
            args[key.strip()] = val
        else:
            if ":" in token or "/" in token:
                args["element"] = token
            else:
                args[token] = True

    return args
