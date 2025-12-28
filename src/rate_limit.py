from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Iterable
from typing import Any

logger = logging.getLogger(__name__)


class RateLimitRegistry:
    """Tracks when a backend/model/key combination can be retried.

    Thread-safety: All public methods use threading.Lock to protect
    concurrent access from multiple threads.
    """

    def __init__(self, max_size: int = 10000) -> None:
        self._until: dict[tuple[str, str, str], float] = {}
        self._max_size = max_size
        self._lock = threading.Lock()

    def set(
        self, backend: str, model: str | None, key_name: str, delay_seconds: float
    ) -> None:
        with self._lock:
            if len(self._until) >= self._max_size:
                self._cleanup_expired()
                if len(self._until) >= self._max_size:
                    # Evict oldest inserted (FIFO behavior with dict)
                    first_key = next(iter(self._until))
                    del self._until[first_key]

            self._until[(backend, model or "", key_name)] = time.time() + delay_seconds

    def _cleanup_expired(self) -> None:
        """Remove expired entries. Caller must hold lock."""
        now = time.time()
        expired_keys = [k for k, ts in self._until.items() if now >= ts]
        for k in expired_keys:
            del self._until[k]

    def get(self, backend: str, model: str | None, key_name: str) -> float | None:
        key = (backend, model or "", key_name)
        with self._lock:
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
        """Return earliest retry timestamp for given combinations."""
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

        with self._lock:
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
        except ValueError as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Malformed retry delay string '%s': %s",
                    delay_str,
                    e,
                    exc_info=True,
                )

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
        # DoS protection: Check string size before parsing
        if len(detail.encode("utf-8")) > 10 * 1024 * 1024:  # 10MB limit
            return None

        try:
            loaded = json.loads(detail)
            return loaded if isinstance(loaded, dict) else None
        except json.JSONDecodeError as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to parse error detail as JSON: %s",
                    e,
                    exc_info=True,
                )
            start = detail.find("{")
            end = detail.rfind("}")
            if start != -1 and end != -1 and end > start:
                # DoS protection: Check extracted JSON size
                json_part = detail[start : end + 1]
                if len(json_part.encode("utf-8")) > 10 * 1024 * 1024:  # 10MB limit
                    return None
                try:
                    loaded = json.loads(json_part)
                    return loaded if isinstance(loaded, dict) else None
                except json.JSONDecodeError as e:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to parse extracted JSON part: %s",
                            e,
                            exc_info=True,
                        )
                    return None
    # Handle None and other non-string, non-dict types
    if detail is None:
        return None
    return None
