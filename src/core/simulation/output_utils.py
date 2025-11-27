"""
Output utilities for safe console printing on Windows.

Handles Unicode encoding issues that occur when printing to Windows console
which uses code pages that can't represent all Unicode characters.
"""

from __future__ import annotations

import sys


def safe_str(text: str, max_length: int | None = None) -> str:
    """Convert text to a console-safe ASCII representation.

    Replaces non-ASCII characters with their Unicode escape sequences
    or descriptive placeholders to avoid encoding errors on Windows console.

    Args:
        text: The text to sanitize
        max_length: Optional maximum length to truncate to

    Returns:
        ASCII-safe string representation
    """
    if max_length is not None and len(text) > max_length:
        text = text[:max_length] + "..."

    # Replace non-ASCII characters with escape sequences
    result = []
    for char in text:
        if ord(char) < 128:
            result.append(char)
        elif ord(char) < 256:
            # Extended ASCII - use hex escape
            result.append(f"\\x{ord(char):02x}")
        else:
            # Unicode - use Unicode escape
            result.append(f"\\u{ord(char):04x}")
    return "".join(result)


def safe_bytes_preview(data: bytes, max_length: int = 100) -> str:
    """Create a safe preview of bytes data for console output.

    Decodes bytes to string and sanitizes for console display.

    Args:
        data: The bytes to preview
        max_length: Maximum number of bytes to include in preview

    Returns:
        ASCII-safe string representation of the data
    """
    preview_data = data[:max_length]
    try:
        # Try to decode as UTF-8 first
        text = preview_data.decode("utf-8", errors="replace")
    except Exception:
        # Fall back to latin-1 which can decode any byte sequence
        text = preview_data.decode("latin-1", errors="replace")

    # Sanitize for console output
    return safe_str(text)


def console_print(*values: object, **kwargs: object) -> None:
    """Print to console with safe encoding for Windows.

    Handles UnicodeEncodeError by replacing problematic characters.
    Accepts the same arguments as the built-in print function.

    Args:
        *values: Values to print
        **kwargs: Keyword arguments passed to print (sep, end, file, flush)
    """
    try:
        # Use builtins.print to avoid any issues
        import builtins

        builtins.print(*values, **kwargs)  # type: ignore[call-overload]
    except UnicodeEncodeError:
        # Fallback: convert all values to safe strings
        import builtins

        safe_values = tuple(safe_str(str(v)) for v in values)
        builtins.print(*safe_values, **kwargs)  # type: ignore[call-overload]


def configure_console_encoding() -> None:
    """Configure console for UTF-8 output if possible.

    On Windows, attempts to set console to UTF-8 mode.
    Falls back gracefully if not possible.
    """
    if sys.platform == "win32":
        try:
            # Try to set console to UTF-8
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleOutputCP(65001)  # UTF-8 code page
        except Exception:
            pass  # Ignore errors, we'll handle encoding issues in print

    # Reconfigure stdout/stderr to use UTF-8 with error handling
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(errors="replace")
    except Exception:
        pass  # Ignore if reconfigure is not available
