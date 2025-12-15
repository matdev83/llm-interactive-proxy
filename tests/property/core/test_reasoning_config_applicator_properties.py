"""Property-based tests for ReasoningConfigApplicator.

Validates:
- Property 9: Reasoning Config Application (Requirements 9.1, 9.2)
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.services.reasoning_config_applicator import ReasoningConfigApplicator

temperature_values = st.floats(
    min_value=0.0,
    max_value=2.0,
    allow_nan=False,
    allow_infinity=False,
)

top_p_values = st.floats(
    min_value=0.0,
    max_value=1.0,
    allow_nan=False,
    allow_infinity=False,
)

top_k_values = st.integers(min_value=1, max_value=512)

thinking_budget_values = st.integers(min_value=0, max_value=1_000_000)


class TestReasoningConfigApplicationProperty:
    """Property 9: Reasoning Config Application (Requirements 9.1, 9.2)."""

    @given(
        temperature=st.none() | temperature_values,
        top_p=st.none() | top_p_values,
        top_k=st.none() | top_k_values,
        reasoning_effort=st.none() | st.sampled_from(["low", "medium", "high"]),
        thinking_budget=st.none() | thinking_budget_values,
    )
    @settings(max_examples=100)
    def test_config_values_applied_to_request_fields(
        self,
        temperature: float | None,
        top_p: float | None,
        top_k: int | None,
        reasoning_effort: str | None,
        thinking_budget: int | None,
    ) -> None:
        """Configured numeric and reasoning parameters are applied when present."""
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="hi")],
        )

        reasoning_mode = SimpleNamespace(
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            reasoning_effort=reasoning_effort,
            thinking_budget=thinking_budget,
            reasoning_config=None,
            gemini_generation_config=None,
            user_prompt_prefix=None,
            user_prompt_suffix=None,
        )

        session = MagicMock()
        session.state = SimpleNamespace(planning_phase_config=None)
        session.get_reasoning_mode = MagicMock(return_value=reasoning_mode)

        result = ReasoningConfigApplicator().apply(request=request, session=session)

        if temperature is None:
            assert result.temperature is None
        else:
            assert isinstance(result.temperature, float)
            assert result.temperature == pytest.approx(float(temperature))

        if top_p is None:
            assert result.top_p is None
        else:
            assert isinstance(result.top_p, float)
            assert result.top_p == pytest.approx(float(top_p))

        if top_k is None:
            assert result.top_k is None
        else:
            assert isinstance(result.top_k, int)
            assert result.top_k == top_k

        assert result.reasoning_effort == reasoning_effort
        assert result.thinking_budget == thinking_budget
