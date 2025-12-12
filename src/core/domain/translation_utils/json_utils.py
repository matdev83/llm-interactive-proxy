from __future__ import annotations

from typing import Any

_MAX_SANITIZE_DEPTH = 100


def _is_json_serializable(
    value: Any,
    *,
    max_depth: int = _MAX_SANITIZE_DEPTH,
    _depth: int = 0,
    _seen: set[int] | None = None,
) -> bool:
    """Best-effort check to determine if a value can be JSON-serialized."""

    if _depth > max_depth:
        return False

    if value is None or isinstance(value, str | int | float | bool):
        return True

    if isinstance(value, list | tuple):
        if _seen is None:
            _seen = set()
        obj_id = id(value)
        if obj_id in _seen:
            return False
        _seen.add(obj_id)
        try:
            return all(
                _is_json_serializable(
                    item,
                    max_depth=max_depth,
                    _depth=_depth + 1,
                    _seen=_seen,
                )
                for item in value
            )
        finally:
            _seen.remove(obj_id)

    if isinstance(value, dict):
        if _seen is None:
            _seen = set()
        obj_id = id(value)
        if obj_id in _seen:
            return False
        _seen.add(obj_id)
        try:
            for key, item in value.items():
                if key is not None and not isinstance(key, str | int | float | bool):
                    return False
                if not _is_json_serializable(
                    item,
                    max_depth=max_depth,
                    _depth=_depth + 1,
                    _seen=_seen,
                ):
                    return False
        finally:
            _seen.remove(obj_id)
        return True

    return False


def _sanitize_dict_for_json(
    data: dict[str, Any],
    *,
    max_depth: int = _MAX_SANITIZE_DEPTH,
    _depth: int = 0,
    _seen: set[int] | None = None,
) -> dict[str, Any]:
    """Sanitize a dictionary by removing or converting non-JSON-serializable values."""

    if _depth > max_depth:
        return {}

    if _seen is None:
        _seen = set()

    obj_id = id(data)
    if obj_id in _seen:
        return {}

    _seen.add(obj_id)
    try:
        sanitized: dict[str, Any] = {}
        sanitized_value: Any = None
        for key, value in data.items():
            if key is not None and not isinstance(key, str | int | float | bool):
                continue

            if _is_json_serializable(
                value,
                max_depth=max_depth,
                _depth=_depth + 1,
                _seen=_seen,
            ):
                sanitized[key] = value
                continue

            if isinstance(value, dict):
                sanitized_value = _sanitize_dict_for_json(
                    value,
                    max_depth=max_depth,
                    _depth=_depth + 1,
                    _seen=_seen,
                )
            elif isinstance(value, list | tuple):
                sanitized_value = _sanitize_list_for_json(
                    value if isinstance(value, list) else list(value),
                    max_depth=max_depth,
                    _depth=_depth + 1,
                    _seen=_seen,
                )
            elif isinstance(value, str | int | float | bool) or value is None:
                sanitized_value = value
            else:
                continue

            sanitized[key] = sanitized_value

        return sanitized
    finally:
        _seen.remove(obj_id)


def _sanitize_list_for_json(
    data: list[Any],
    *,
    max_depth: int = _MAX_SANITIZE_DEPTH,
    _depth: int = 0,
    _seen: set[int] | None = None,
) -> list[Any]:
    """Sanitize a list by removing or converting non-JSON-serializable items."""

    if _depth > max_depth:
        return []

    if _seen is None:
        _seen = set()

    obj_id = id(data)
    if obj_id in _seen:
        return []

    _seen.add(obj_id)
    try:
        sanitized: list[Any] = []
        for item in data:
            if _is_json_serializable(
                item,
                max_depth=max_depth,
                _depth=_depth + 1,
                _seen=_seen,
            ):
                sanitized.append(item)
                continue

            if isinstance(item, dict):
                sanitized.append(
                    _sanitize_dict_for_json(
                        item,
                        max_depth=max_depth,
                        _depth=_depth + 1,
                        _seen=_seen,
                    )
                )
            elif isinstance(item, list | tuple):
                sanitized.append(
                    _sanitize_list_for_json(
                        item if isinstance(item, list) else list(item),
                        max_depth=max_depth,
                        _depth=_depth + 1,
                        _seen=_seen,
                    )
                )
            elif isinstance(item, str | int | float | bool) or item is None:
                sanitized.append(item)
            else:
                continue

        return sanitized
    finally:
        _seen.remove(obj_id)


def is_json_serializable(value: Any, *, max_depth: int = _MAX_SANITIZE_DEPTH) -> bool:
    return _is_json_serializable(value, max_depth=max_depth)


def sanitize_dict_for_json(
    data: dict[str, Any], *, max_depth: int = _MAX_SANITIZE_DEPTH
) -> dict[str, Any]:
    return _sanitize_dict_for_json(data, max_depth=max_depth)


def sanitize_list_for_json(
    data: list[Any], *, max_depth: int = _MAX_SANITIZE_DEPTH
) -> list[Any]:
    return _sanitize_list_for_json(data, max_depth=max_depth)
