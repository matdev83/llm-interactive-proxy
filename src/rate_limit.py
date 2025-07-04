from __future__ import annotations

from typing import Dict, Tuple, Optional
import time
import json

class RateLimitRegistry:
    """Tracks when a backend/model/key combination can be retried."""

    def __init__(self) -> None:
        self._until: Dict[Tuple[str, str, str], float] = {}

    def set(self, backend: str, model: str | None, key_name: str, delay_seconds: float) -> None:
        self._until[(backend, model or "", key_name)] = time.time() + delay_seconds

    def get(self, backend: str, model: str | None, key_name: str) -> Optional[float]:
        key = (backend, model or "", key_name)
        ts = self._until.get(key)
        if ts is None:
            return None
        if time.time() >= ts:
            del self._until[key]
            return None
        return ts

def _detail_to_dict(detail: object) -> Optional[Dict]:
    """Converts detail to a dictionary if it's a JSON string, otherwise returns as is."""
    if isinstance(detail, str):
        try:
            return json.loads(detail)
        except json.JSONDecodeError:
            return None
    if isinstance(detail, dict):
        return detail
    return None

def _find_retry_info_item(details_list: list) -> Optional[Dict]:
    """Finds the RetryInfo item in a list of detail items."""
    for item in details_list:
        if isinstance(item, dict) and item.get("@type", "").endswith("RetryInfo"):
            return item
    return None

def _extract_delay_seconds(retry_info_item: Dict) -> Optional[float]:
    """Extracts and converts retryDelay string (e.g., "1.234s") to float seconds."""
    delay_str = retry_info_item.get("retryDelay")
    if isinstance(delay_str, str) and delay_str.endswith("s"):
        try:
            return float(delay_str[:-1])
        except ValueError:
            return None
    return None

def parse_retry_delay(detail: object) -> Optional[float]:
    """Parse retry delay (seconds) from backend 429 error details."""
    data_dict = _detail_to_dict(detail)
    if not data_dict:
        return None

    # The error structure can be data itself or nested under "error"
    error_content = data_dict.get("error", data_dict)
    if not isinstance(error_content, dict):
        return None

    details_list = error_content.get("details")
    if not isinstance(details_list, list):
        return None

    retry_info_item = _find_retry_info_item(details_list)
    if not retry_info_item:
        return None

    return _extract_delay_seconds(retry_info_item)
