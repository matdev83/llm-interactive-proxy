from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Iterable
from typing import Any, MutableMapping

from cachetools import TTLCache

logger = logging.getLogger(__name__)


class RateLimitRegistry:
    """Tracks when a backend/model/key combination can be retried.

    Thread-safety: All public methods use threading.Lock to protect
    concurrent access from multiple threads.
    """

    def __init__(self, max_size: int = 10000) -> None:
        self._until: MutableMapping[tuple[str, str, str], float] = TTLCache(
            maxsize=max_size, ttl=365 * 24 * 60 * 60
        )
        self._lock = threading.Lock()

    def set(
        self, backend: str, model: str | None, key_name: str, delay_seconds: float
    ) -> None:
        with self._lock:
            self._until[(backend, model or "", key_name)] = time.time() + delay_seconds

    def get(self, backend: str, model: str | None, key_name: str) -> float | None:
        key = (backend, model or "", key_name)
        with self._lock:
            ts = self._until.get(key)
            if ts is None:
                return None
            if time.time() >= ts:
                # This entry should have been expired by TTLCache, but if not
                # (e.g. if accessed before its TTL but after its time.time() expiry),
                # ensure it's removed and treated as expired.
                # TTLCache's eviction is based on LRU when maxsize is hit,
                # and TTL when an item is accessed after its TTL.
                # Direct time-based check provides an additional layer of certainty for
                # correctness, even if the item is still in cache.
                try:
                    del self._until[key]
                except KeyError:
                    pass
                return None
            return ts

    def earliest(
        self, combos: Iterable[tuple[str, str, str]] | None = None
    ) -> float | None:
        """Return earliest retry timestamp for given combinations."""
        now = time.time()
        valid_times: list[float] = []

        with self._lock:
            if combos is None or not combos: # Changed: handle empty list like None
                # Iterate over all items in the cache
                for key, ts in list(self._until.items()):  # Use list() to iterate over a copy
                    if now >= ts:
                        try:
                            del self._until[key]
                        except KeyError:
                            pass
                        continue
                    valid_times.append(ts)
            else:
                for backend, model, key_name in combos:
                    key = (backend, model or "", key_name)
                    ts = self._until.get(key)
                    if ts is None:
                        continue
                    if now >= ts:
                        try:
                            del self._until[key]
                        except KeyError:
                            pass
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
