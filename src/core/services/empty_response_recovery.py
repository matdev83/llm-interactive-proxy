"""Backward-compatible empty response recovery shim.

Historically the EmptyResponseRecovery helper exposed an async
``retry_if_needed`` method that always returned ``None`` unless an empty
response warranted a retry. The newer middleware implementation handles the
logic directly, but tests and integrations still import the helper.  This shim
keeps the public contract intact without reintroducing redundant behavior.
"""

from __future__ import annotations

from typing import Any


class EmptyResponseRecovery:
    """No-op recovery helper maintained for API compatibility."""

    async def retry_if_needed(
        self,
        context: Any,
        request: Any,
        response: Any,
    ) -> None:
        """Preserve the legacy coroutine signature and return ``None``."""

        return None
