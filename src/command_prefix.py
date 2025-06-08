import string


def validate_command_prefix(prefix: str) -> str | None:
    """Return error message if prefix is invalid, otherwise None."""
    if not isinstance(prefix, str) or not prefix:
        return "command prefix must be a non-empty string"
    if any(c.isspace() for c in prefix):
        return "command prefix cannot contain whitespace"
    if len(prefix) < 2:
        return "command prefix must be at least 2 characters"
    if len(prefix) > 10:
        return "command prefix must not exceed 10 characters"
    if not all(c in string.printable and not c.isspace() for c in prefix):
        return "command prefix must contain only printable non-whitespace characters"
    if len(prefix) == 2 and prefix[0] == prefix[1]:
        return "two character prefixes cannot repeat the same character"
    return None

