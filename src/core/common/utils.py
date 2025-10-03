from __future__ import annotations

import fnmatch


def wildcard_match(pattern: str, name: str) -> bool:
    """
    Checks if a name matches a pattern with wildcards.

    Args:
        pattern: The pattern to match against.
        name: The name to check.

    Returns:
        True if the name matches the pattern, False otherwise.
    """
    return fnmatch.fnmatch(name, pattern)
