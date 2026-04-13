"""Tests for empty upstream chunk iterators used by ResponsesController."""

from __future__ import annotations

from typing import Any

import pytest
from src.core.app.controllers.responses_controller import (
    _empty_responses_chunk_iterator,
)


@pytest.mark.asyncio
async def test_empty_responses_chunk_iterator_emits_nothing() -> None:
    """Empty upstream chunk iterator must not yield before exhaustion."""

    seen: list[Any] = []
    async for item in _empty_responses_chunk_iterator():
        seen.append(item)
    assert seen == []

    agen = _empty_responses_chunk_iterator()
    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()
