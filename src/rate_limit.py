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
        now = time.time()

        if combos:
            keys = [(b, m or "", k) for b, m, k in combos]
        else:
            keys = list(self._until.keys())

        valid_times: list[float] = []
        for key in keys:
            ts = self._until.get(key)
            if ts is None:
                continue

            if now >= ts:
                # Expired entry; clean it up to keep the registry accurate
                self._until.pop(key, None)
                continue

            valid_times.append(ts)

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

        delay_value = item.get("retryDelay")

        if isinstance(delay_value, str):
            if not delay_value.endswith("s"):
                continue

            try:
                return float(delay_value[:-1])
            except ValueError:
                continue

        if isinstance(delay_value, dict):
            seconds_value = delay_value.get("seconds", 0)
            nanos_value = delay_value.get("nanos", 0)

            try:
                seconds = float(seconds_value)
            except (TypeError, ValueError):
                continue

            try:
                nanos = float(nanos_value)
            except (TypeError, ValueError):
                nanos = 0.0

            return seconds + nanos / 1_000_000_000

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
