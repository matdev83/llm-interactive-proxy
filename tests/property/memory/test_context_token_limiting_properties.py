"""Property-based tests for context token limiting.

Feature: proxy-mem
Property: 9
Validates: Requirements 11.4 - Context token limiting
"""

from __future__ import annotations

from typing import cast

from hypothesis import HealthCheck, given
from hypothesis import strategies as st
from src.core.memory.config import MemoryConfiguration
from src.core.memory.context_injector import ContextInjector
from src.core.memory.repository import IMemoryRepository
from tests.utils.hypothesis_config import property_test_settings


class _StubRepository:
    async def get_recent_sessions(
        self, *args: object, **kwargs: object
    ) -> list[object]:
        return []


@given(
    max_tokens=st.integers(min_value=1, max_value=200),
    context_len=st.integers(min_value=0, max_value=2000),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
def test_property_9_context_truncated_to_token_limit(
    max_tokens: int,
    context_len: int,
) -> None:
    """Context is truncated when exceeding the configured token cap."""
    config = MemoryConfiguration(max_context_tokens=max_tokens)
    injector = ContextInjector(
        config=config,
        repository=cast(IMemoryRepository, _StubRepository()),
    )

    context = "x" * context_len
    result = injector._limit_tokens(context)

    max_chars = max_tokens * 4
    if context_len == 0:
        assert result is None
        return

    assert result is not None
    if context_len <= max_chars:
        assert result == context
    else:
        assert "[Context truncated due to token limit]" in result
        assert (
            len(result) <= max_chars + len("[Context truncated due to token limit]") + 2
        )
