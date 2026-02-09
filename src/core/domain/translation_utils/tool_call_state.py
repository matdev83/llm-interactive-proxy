from __future__ import annotations

import threading
from collections.abc import MutableMapping
from typing import Any

from cachetools import TTLCache  # type: ignore

codex_tool_call_index_base: MutableMapping[str, int] = TTLCache(maxsize=1000, ttl=600)
codex_tool_call_item_index: MutableMapping[str, dict[str, int]] = TTLCache(
    maxsize=1000, ttl=600
)
codex_function_name_cache: MutableMapping[str, str] = TTLCache(maxsize=1000, ttl=600)
_tool_state_lock = threading.Lock()


def reset_tool_call_state(response_id: str | None) -> None:
    if not response_id:
        return
    with _tool_state_lock:
        codex_tool_call_index_base.pop(response_id, None)
        codex_tool_call_item_index.pop(response_id, None)


def cache_function_name(call_id: str, name: str) -> None:
    if call_id and name:
        with _tool_state_lock:
            codex_function_name_cache[call_id] = name


def get_cached_function_name(call_id: str) -> str:
    with _tool_state_lock:
        return codex_function_name_cache.get(call_id, "")


def assign_tool_call_index(
    response_id: str | None,
    output_index: Any,
    item_id: str | None,
) -> int:
    if not response_id:
        return 0

    if not isinstance(output_index, int):
        if item_id:
            with _tool_state_lock:
                item_index_dict = codex_tool_call_item_index.get(response_id, {})
                return item_index_dict.get(item_id, 0) if item_index_dict else 0
        return 0

    with _tool_state_lock:
        base = codex_tool_call_index_base.get(response_id)
        if base is None or output_index < base:
            codex_tool_call_index_base[response_id] = output_index
            base = output_index

        index = output_index - base
        if index < 0:
            index = 0

        if item_id:
            item_dict = codex_tool_call_item_index.setdefault(response_id, {})
            item_dict[item_id] = index

        return index
