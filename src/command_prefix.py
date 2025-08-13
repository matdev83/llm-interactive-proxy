import string

# Define rules outside the function so they are created only once.
# Each rule is a tuple: (lambda predicate returning True on error, error_message)
# These rules assume `prefix` is already confirmed to be a non-empty string.
_PREFIX_VALIDATION_RULES = [
    (lambda p: any(c.isspace() for c in p), "command prefix cannot contain whitespace"),
    (lambda p: len(p) < 2, "command prefix must be at least 2 characters"),
    (lambda p: len(p) > 10, "command prefix must not exceed 10 characters"),
    # This rule assumes whitespace has been checked:
    # if it passed the 'any space' check, then all chars are non-whitespace.
    # So, we only need to check if they are printable.
    (
        lambda p: not all(c in string.printable for c in p),
        "command prefix must contain only printable characters",
    ),
    (
        lambda p: len(p) == 2 and p[0] == p[1],
        "two character prefixes cannot repeat the same character",
    ),
]


def validate_command_prefix(prefix: str) -> str | None:
    """Return error message if prefix is invalid, otherwise None."""
    # Initial type and emptiness check - crucial before other lambda checks
    if not isinstance(prefix, str) or not prefix:
        return "command prefix must be a non-empty string"

    for check, message in _PREFIX_VALIDATION_RULES:
        if check(prefix):  # type: ignore[no-untyped-call]
            return message

    return None
