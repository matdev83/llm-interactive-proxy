from __future__ import annotations

from typing import Any, MutableMapping

from cachetools import TTLCache

_codex_tool_call_index_base: MutableMapping[str, int] = TTLCache(maxsize=1000, ttl=600)
_codex_tool_call_item_index: MutableMapping[str, dict[str, int]] = TTLCache(maxsize=1000, ttl=600)
_codex_function_name_cache: MutableMapping[str, str] = TTLCache(maxsize=1000, ttl=600)


def reset_tool_call_state(response_id: str | None) -> None:
    if not response_id:
        return
    _codex_tool_call_index_base.pop(response_id, None)
    _codex_tool_call_item_index.pop(response_id, None)


def cache_function_name(call_id: str, name: str) -> None:
    if call_id and name:
        _codex_function_name_cache[call_id] = name


def get_cached_function_name(call_id: str) -> str:
    return _codex_function_name_cache.get(call_id, "")


def assign_tool_call_index(
    response_id: str | None,
    output_index: Any,
    item_id: str | None,
) -> int:
    if not response_id:
        return 0

    if not isinstance(output_index, int):
        if item_id:
            return _codex_tool_call_item_index.get(response_id, {}).get(item_id, 0)
        return 0

    base = _codex_tool_call_index_base.get(response_id)
    if base is None or output_index < base:
        _codex_tool_call_index_base[response_id] = output_index
        base = output_index

    index = output_index - base
    if index < 0:
        index = 0

    if item_id:
        _codex_tool_call_item_index.setdefault(response_id, {})[item_id] = index

    return index
