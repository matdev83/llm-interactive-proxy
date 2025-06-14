from __future__ import annotations

import json
import time
from typing import Dict, Optional, Tuple


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


def parse_retry_delay(detail: object) -> Optional[float]:
    """Parse retry delay (seconds) from backend 429 error details."""
    data: object = detail
    if isinstance(detail, str):
        try:
            data = json.loads(detail)
        except Exception:
            return None
    if isinstance(data, dict):
        err = data.get("error", data)
        details = err.get("details") if isinstance(err, dict) else None
        if isinstance(details, list):
            for item in details:
                if isinstance(item, dict) and item.get("@type", "").endswith(
                    "RetryInfo"
                ):
                    delay = item.get("retryDelay")
                    if isinstance(delay, str) and delay.endswith("s"):
                        try:
                            return float(delay[:-1])
                        except ValueError:
                            pass
    return None
