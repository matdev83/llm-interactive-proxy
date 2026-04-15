"""Utility functions for OpenAI Codex connector components."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
from collections.abc import Mapping, Sequence
from typing import Any

from src.core.app.constants.logging_constants import TRACE_LEVEL

logger = logging.getLogger(__name__)


def sanitize_header_value(value: str) -> str:
    """Replace characters outside the visible ASCII range with underscores."""
    return "".join(ch if 32 <= ord(ch) <= 126 else "_" for ch in value)


def detect_terminal_user_agent() -> str:
    """Best effort reproduction of codex-rs terminal::user_agent detection."""
    term_program = os.getenv("TERM_PROGRAM", "").strip()
    if term_program:
        version = os.getenv("TERM_PROGRAM_VERSION", "").strip()
        base = f"{term_program}/{version}" if version else term_program
    elif wez := os.getenv("WEZTERM_VERSION", "").strip():
        base = f"WezTerm/{wez}" if wez else "WezTerm"
    elif os.getenv("KITTY_WINDOW_ID") or "kitty" in os.getenv("TERM", ""):
        base = "kitty"
    elif os.getenv("ALACRITTY_SOCKET") or os.getenv("TERM", "") == "alacritty":
        base = "Alacritty"
    elif konsole := os.getenv("KONSOLE_VERSION", "").strip():
        base = f"Konsole/{konsole}" if konsole else "Konsole"
    elif os.getenv("GNOME_TERMINAL_SCREEN"):
        base = "gnome-terminal"
    elif vte := os.getenv("VTE_VERSION", "").strip():
        base = f"VTE/{vte}" if vte else "VTE"
    elif os.getenv("WT_SESSION"):
        base = "WindowsTerminal"
    else:
        base = os.getenv("TERM", "unknown")
    return sanitize_header_value(base)


def build_codex_user_agent(
    originator: str = "codex_cli_rs", version: str = "0.0.0"
) -> str:
    """Build a Codex CLI compatible User-Agent string."""
    system_name = platform.system() or "UnknownOS"
    system_version = (
        platform.version() or platform.release() or os.environ.get("OS", "0")
    )
    arch = platform.machine() or "unknown"
    terminal = detect_terminal_user_agent()
    base = (
        f"{originator}/{version} "
        f"({system_name} {system_version}; {arch}; {terminal}) {terminal}"
    )
    sanitized = sanitize_header_value(base)
    if sanitized.strip():
        return sanitized
    return f"{originator}/{version}"


def load_json_env(var_name: str) -> Any:
    """Parse a JSON environment variable, returning None on failure."""
    raw_value = os.getenv(var_name)
    if not raw_value:
        return None
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        logger.warning("Ignoring invalid JSON in %s", var_name, exc_info=True)
        return None


def message_to_text(message: Any) -> str:
    """Best-effort conversion of a ChatMessage-like object to plain text."""
    # Prefer explicit attributes
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
                    continue
            if (
                not isinstance(part, dict)
                and hasattr(part, "model_dump")
                and callable(part.model_dump)
            ):
                dumped = part.model_dump()
                if isinstance(dumped, dict):
                    text = dumped.get("text")
                    if isinstance(text, str):
                        parts.append(text)
                        continue
            parts.append(str(part))
        return "\n".join(parts)

    if content is not None:
        return str(content)

    # Fallback to message string representation
    return str(message)


def to_mapping(candidate: Any) -> dict[str, Any] | None:
    """Convert arbitrary objects into plain dictionaries when possible."""
    if candidate is None:
        return None
    if isinstance(candidate, Mapping):
        return dict(candidate)
    if hasattr(candidate, "model_dump") and callable(candidate.model_dump):
        try:
            dumped = candidate.model_dump()
            if isinstance(dumped, Mapping):
                return dict(dumped)
        except (TypeError, AttributeError, ValueError) as e:
            if logger.isEnabledFor(TRACE_LEVEL):
                logger.log(
                    TRACE_LEVEL,
                    "Failed to convert model_dump result to mapping: %s (type=%s)",
                    str(e),
                    type(e).__name__,
                    exc_info=True,
                )
            return None
    if hasattr(candidate, "__dict__"):
        return dict(candidate.__dict__)
    return None


def coerce_positive_int(value: Any) -> int | None:
    """Return a positive int coerced from arbitrary input."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str):
        if not value.strip().isdigit():
            return None
        numeric = int(value.strip())
        return numeric if numeric >= 0 else None
    return None


def coerce_float_sequence(value: Any) -> tuple[float, ...] | None:
    """Convert a value into a tuple of non-negative floats."""
    if value is None:
        return None
    if isinstance(value, list | tuple | set):
        result: list[float] = []
        for item in value:
            try:
                numeric = float(item)
            except (TypeError, ValueError):
                continue
            if numeric < 0:
                continue
            result.append(numeric)
        return tuple(result)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parts = [part.strip() for part in value.split(",")]
            return coerce_float_sequence(parts)
        else:
            return coerce_float_sequence(parsed)
    return None


def json_default(value: Any) -> Any:
    """Default JSON encoder for pydantic models and other objects."""
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return str(value)


def fingerprint_component(value: Any) -> str | None:
    """Create a stable SHA256 hash of a JSON-serializable component."""
    if value is None:
        return None
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=json_default,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def fingerprint_input_items(value: Any) -> tuple[str, ...]:
    """Create stability fingerprints for a list of input items."""
    if not isinstance(value, list):
        return ()
    fingerprints: list[str] = []
    for item in value:
        encoded = json.dumps(
            item,
            sort_keys=True,
            separators=(",", ":"),
            default=json_default,
        ).encode("utf-8")
        fingerprints.append(hashlib.sha256(encoded).hexdigest())
    return tuple(fingerprints)


def to_string_list(value: Any) -> list[str]:
    """Normalize various containers into a list of non-empty strings."""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
        result: list[str] = []
        for item in value:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    result.append(text)
        return result
    return []


def validate_tool_schema(
    schema: dict[str, Any], context: str
) -> tuple[bool, list[str]]:
    """Validate a tool schema dictionary.

    Returns:
        (is_valid, list_of_errors)
    """
    errors: list[str] = []

    # Required: name field
    name = schema.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append(f"{context}: Missing or invalid 'name' field")

    # Optional but recommended: description
    if "description" in schema:
        desc = schema.get("description")
        if not isinstance(desc, str):
            errors.append(f"{context}: 'description' must be a string")

    # Optional but common: parameters
    if "parameters" in schema:
        params = schema.get("parameters")
        if not isinstance(params, dict):
            errors.append(f"{context}: 'parameters' must be an object")
        elif "type" in params and params.get("type") != "object":
            errors.append(f"{context}: 'parameters.type' should be 'object'")

    return len(errors) == 0, errors


def normalize_tool_schema_list(value: Any, *, context: str) -> list[dict[str, Any]]:
    """Normalize a value into a list of tool schema dictionaries with validation."""
    if value is None:
        return []
    items: Sequence[Any]
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        items = value
    else:
        items = [value]
    normalized: list[dict[str, Any]] = []
    for idx, entry in enumerate(items):
        mapping = to_mapping(entry)
        if not mapping:
            logger.warning(
                "Skipping invalid tool schema entry %s[%s]: not a valid mapping",
                context,
                idx,
            )
            continue

        # Validate the schema
        is_valid, errors = validate_tool_schema(mapping, f"{context}[{idx}]")
        if not is_valid:
            logger.warning(
                "Skipping invalid tool schema entry %s[%s]: %s",
                context,
                idx,
                "; ".join(errors),
            )
            continue

        normalized.append(dict(mapping))
    return normalized
