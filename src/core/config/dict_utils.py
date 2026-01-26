from __future__ import annotations

import re
from typing import Any


def merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge override into base (mutates and returns base).

    Args:
        base: Base dictionary to merge into
        override: Override dictionary with values to merge

    Returns:
        The merged base dictionary
    """
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            merge_dicts(base[key], value)
        else:
            base[key] = value
    return base


_SIMPLE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _needs_brackets(key: str) -> bool:
    return (
        "." in key
        or "[" in key
        or "]" in key
        or '"' in key
        or "\\" in key
        or not _SIMPLE_KEY_RE.fullmatch(key)
    )


def _escape_key(key: str) -> str:
    return key.replace("\\", "\\\\").replace('"', '\\"')


def _append_path(prefix: str, key: str) -> str:
    if _needs_brackets(key):
        segment = f'["{_escape_key(key)}"]'
        return f"{prefix}{segment}" if prefix else segment
    return f"{prefix}.{key}" if prefix else key


def _parse_path(path: str) -> list[str]:
    parts: list[str] = []
    i = 0
    while i < len(path):
        if path[i] == ".":
            i += 1
            continue
        if path[i] == "[":
            if path.startswith('["', i):
                i += 2
                buf: list[str] = []
                while i < len(path):
                    ch = path[i]
                    if ch == "\\":
                        if i + 1 >= len(path):
                            raise ValueError(f"Invalid escape in path: {path}")
                        buf.append(path[i + 1])
                        i += 2
                        continue
                    if ch == '"':
                        break
                    buf.append(ch)
                    i += 1
                if i >= len(path) or path[i] != '"':
                    raise ValueError(f"Unterminated bracket key in path: {path}")
                i += 1
                if i >= len(path) or path[i] != "]":
                    raise ValueError(f"Unterminated bracket key in path: {path}")
                i += 1
                parts.append("".join(buf))
                continue

            # Support numeric index like [0]
            start = i + 1
            i = start
            while i < len(path) and path[i].isdigit():
                i += 1
            if i > start and i < len(path) and path[i] == "]":
                parts.append(path[start:i])
                i += 1
                continue

            raise ValueError(f"Unsupported path syntax near: {path[i:]}")

        start = i
        while i < len(path) and path[i] not in ".[":
            i += 1
        parts.append(path[start:i])
    return parts


def set_by_path(target: dict[str, Any], path: str, value: Any) -> None:
    parts = _parse_path(path)
    if not parts:
        raise ValueError("Empty path")
    current: dict[str, Any] = target
    for key in parts[:-1]:
        existing = current.get(key)
        if not isinstance(existing, dict):
            current[key] = {}
        current = current[key]
    current[parts[-1]] = value


def get_by_path(source: dict[str, Any], path: str) -> dict[str, Any] | None:
    parts = _parse_path(path)
    if not parts:
        return None
    current: dict[str, Any] | None = source
    for key in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def flatten_dict(data: dict[str, Any]) -> dict[str, Any]:
    flattened: dict[str, Any] = {}

    def _walk(value: Any, prefix: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                new_prefix = _append_path(prefix, str(key))
                _walk(child, new_prefix)
        else:
            flattened[prefix] = value

    _walk(data, "")
    return flattened
