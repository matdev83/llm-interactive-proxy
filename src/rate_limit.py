from __future__ import annotations

import json
import time
from collections.abc import Iterable
from typing import Any


class RateLimitRegistry:
    """Tracks when a backend/model/key combination can be retried."""

    def __init__(self) -> None:
        self._until: dict[tuple[str, str, str], float] = {}

    def set(
        self, backend: str, model: str | None, key_name: str, delay_seconds: float
    ) -> None:
        self._until[(backend, model or "", key_name)] = time.time() + delay_seconds

    def get(self, backend: str, model: str | None, key_name: str) -> float | None:
        key = (backend, model or "", key_name)
        ts = self._until.get(key)
        if ts is None:
            return None
        if time.time() >= ts:
            del self._until[key]
            return None
        return ts

    def earliest(
        self, combos: Iterable[tuple[str, str, str]] | None = None
    ) -> float | None:
        """Return the earliest retry timestamp for the given combinations."""
        keys: Iterable[tuple[str, str, str]]
        if combos is None:
            keys = list(self._until.keys())
        else:
            combos_list = list(combos)
            if (
                not combos_list
            ):  # Empty list should fall back to all entries (preserve original behavior)
                keys = list(self._until.keys())
            else:
                keys = [
                    (backend, model or "", key_name)
                    for backend, model, key_name in combos_list
                ]
        now = time.time()
        valid_times: list[float] = []
        expired_keys: list[tuple[str, str, str]] = []

        for key in keys:
            ts = self._until.get(key)
            if ts is None:
                continue
            if now >= ts:
                expired_keys.append(key)
                continue
            valid_times.append(ts)

        for key in expired_keys:
            self._until.pop(key, None)

        if not valid_times:
            return None
        return min(valid_times)


def _find_retry_delay_in_details(details_list: list[Any]) -> float | None:
    """Iterates through a list of detail items to find and parse RetryInfo."""
    # This check can be removed if the caller ensures details_list is always a list.
    # However, keeping it makes the helper more robust.
    if not isinstance(details_list, list):  # type: ignore[unreachable]
        return None  # type: ignore[unreachable]

    for item in details_list:
        if not isinstance(item, dict):
            continue

        if not item.get("@type", "").endswith("RetryInfo"):
            continue

        delay_str = item.get("retryDelay")
        if not isinstance(delay_str, str) or not delay_str.endswith("s"):
            continue

        try:
            return float(delay_str[:-1])
        except ValueError:
            pass  # Malformed delay string in this item, try next

    return None


def parse_retry_delay(detail: object) -> float | None:
    """Parse retry delay (seconds) from backend 429 error details."""
    data_dict = _as_dict(detail)
    if not data_dict:
        return None
    err_obj = data_dict.get("error", data_dict)
    if not isinstance(err_obj, dict):
        return None
    details = err_obj.get("details")
    if not isinstance(details, list):
        return None
    return _find_retry_delay_in_details(details)


def _as_dict(detail: object) -> dict[str, Any] | None:
    """Best-effort conversion of an error detail payload into a dict."""
    if isinstance(detail, dict):
        return detail
    if isinstance(detail, str):
        try:
            loaded = json.loads(detail)
            return loaded if isinstance(loaded, dict) else None
        except json.JSONDecodeError:
            start = detail.find("{")
            end = detail.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    loaded = json.loads(detail[start : end + 1])
                    return loaded if isinstance(loaded, dict) else None
                except json.JSONDecodeError:
                    return None
    return None
