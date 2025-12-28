"""Property-based tests for summary completion token cap.

Feature: proxy-mem
Property: 21
Validates: Requirements 9.11 - Summary completion token cap
"""

from __future__ import annotations

from typing import cast

import pytest
from hypothesis import HealthCheck, given
from hypothesis import strategies as st
from src.core.memory.config import MemoryConfiguration
from src.core.memory.repository import IMemoryRepository
from src.core.memory.summary_generator import SummaryGenerator
from tests.utils.hypothesis_config import property_test_settings


class _StubRepository:
    async def initialize_schema(self) -> None:
        return None

    async def save_session_summary(self, summary: object) -> None:
        return None

    async def get_recent_sessions(
        self, *args: object, **kwargs: object
    ) -> list[object]:
        return []

    async def delete_old_sessions(self, *args: object, **kwargs: object) -> int:
        return 0

    async def get_or_create_project_id(self, *args: object, **kwargs: object) -> str:
        return "proj-1"


class _Recorder:
    def __init__(self) -> None:
        self.max_tokens: int | None = None

    async def __call__(self, prompt: str, *, max_tokens: int | None = None) -> str:
        self.max_tokens = max_tokens
        return "ok"


@given(token_cap=st.integers(min_value=1, max_value=20000))
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
@pytest.mark.asyncio
async def test_property_21_summary_completion_cap_passed_to_llm(
    token_cap: int,
) -> None:
    """Summary generator passes completion cap to LLM caller."""
    recorder = _Recorder()
    config = MemoryConfiguration(summary_completion_tokens=token_cap)
    generator = SummaryGenerator(
        config=config,
        repository=cast(IMemoryRepository, _StubRepository()),
        llm_caller=recorder,
    )

    result = await generator._call_llm_with_retry("prompt")
    assert result == "ok"
    assert recorder.max_tokens == token_cap
