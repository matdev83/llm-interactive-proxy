import asyncio
import time

import pytest
from src.core.ports.streaming_orchestrator import safe_aclose


class _HungAclose:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:  # pragma: no cover - intentionally hung
        # Simulate a transport/SDK that never completes close.
        await asyncio.Event().wait()
        self.closed = True


@pytest.mark.asyncio
async def test_safe_aclose_times_out_on_hung_aclose() -> None:
    stream = _HungAclose()

    start = time.monotonic()
    await safe_aclose(stream, provider="test", stream_id="sid", timeout_s=0.05)
    elapsed = time.monotonic() - start

    # Should return promptly instead of hanging.
    assert elapsed < 0.5
