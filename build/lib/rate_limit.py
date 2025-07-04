from __future__ import annotations

import json
import time
from typing import Dict, Optional, Tuple, Any


class RateLimitRegistry:
    """Tracks when a backend/model/key combination can be retried."""

    def __init__(self) -> None:
        self._until: Dict[Tuple[str, str, str], float] = {}

    def set(
            self,
            backend: str,
            model: str | None,
            key_name: str,
            delay_seconds: float) -> None:
        self._until[(backend, model or "", key_name)
                    ] = time.time() + delay_seconds

    def get(self, backend: str, model: str | None,
            key_name: str) -> Optional[float]:
        key = (backend, model or "", key_name)
        ts = self._until.get(key)
        if ts is None:
            return None
        if time.time() >= ts:
            del self._until[key]
            return None
        return ts


def _find_retry_delay_in_details(details_list: list) -> Optional[float]:
    """Iterates through a list of detail items to find and parse RetryInfo."""
    # This check can be removed if the caller ensures details_list is always a list.
    # However, keeping it makes the helper more robust.
    if not isinstance(details_list, list):
        return None

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
            pass # Malformed delay string in this item, try next

    return None


def parse_retry_delay(detail: object) -> Optional[float]:
    """Parse retry delay (seconds) from backend 429 error details."""
    data_dict: Optional[Dict[str, Any]] = None
    if isinstance(detail, str):
        try:
            loaded_json = json.loads(detail)
            if isinstance(loaded_json, dict):
                data_dict = loaded_json
            else: # Loaded JSON is not a dictionary
                return None
        except json.JSONDecodeError: # Catch specific error
            return None
    elif isinstance(detail, dict):
        data_dict = detail

    if not data_dict:
        return None

    err_obj = data_dict.get("error", data_dict)
    if not isinstance(err_obj, dict):
        return None

    details = err_obj.get("details")
    # _find_retry_delay_in_details will handle if details is None or not a list,
    # but explicit check here keeps parse_retry_delay cleaner about what it passes.
    if not isinstance(details, list):
        return None

    return _find_retry_delay_in_details(details)
