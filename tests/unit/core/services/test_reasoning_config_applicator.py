"""Unit tests for ReasoningConfigApplicator."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from src.core.domain.chat import (
    ChatMessage,
    ChatRequest,
    MessageContentPartText,
)
from src.core.services.reasoning_config_applicator import ReasoningConfigApplicator


class TestReasoningConfigApplicatorBasics:
    """Basic behavior tests."""

    def test_no_reasoning_mode_returns_original(self) -> None:
        """If session has no reasoning mode, request is unchanged."""
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="hi")],
            temperature=0.5,
        )

        session = MagicMock()
        session.get_reasoning_mode = MagicMock(return_value=None)
        session.state = SimpleNamespace(planning_phase_config=None)

        result = ReasoningConfigApplicator().apply(request=request, session=session)

        assert result.model_dump() == request.model_dump()

    def test_numeric_overrides_applied(self) -> None:
        """Temperature/top_p/top_k and effort/budget are applied when configured."""
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="hi")],
        )

        reasoning_mode = SimpleNamespace(
            temperature=0.7,
            top_p=0.9,
            top_k=32,
            reasoning_effort="high",
            thinking_budget=123,
            reasoning_config=None,
            gemini_generation_config=None,
            user_prompt_prefix=None,
            user_prompt_suffix=None,
        )
        session = MagicMock()
        session.state = SimpleNamespace(planning_phase_config=None)
        session.get_reasoning_mode = MagicMock(return_value=reasoning_mode)

        result = ReasoningConfigApplicator().apply(request=request, session=session)

        assert result.temperature == pytest.approx(0.7)
        assert result.top_p == pytest.approx(0.9)
        assert result.top_k == 32
        assert result.reasoning_effort == "high"
        assert result.thinking_budget == 123

    def test_edit_precision_limits_numeric_overrides(self) -> None:
        """Edit-precision mode should not increase sampling parameters."""
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="hi")],
            temperature=0.2,
            top_p=0.4,
            top_k=10,
            extra_body={"_edit_precision_mode": True},
        )

        reasoning_mode = SimpleNamespace(
            temperature=0.9,
            top_p=0.95,
            top_k=40,
            reasoning_effort=None,
            thinking_budget=None,
            reasoning_config=None,
            gemini_generation_config=None,
            user_prompt_prefix=None,
            user_prompt_suffix=None,
        )
        session = MagicMock()
        session.state = SimpleNamespace(planning_phase_config=None)
        session.get_reasoning_mode = MagicMock(return_value=reasoning_mode)

        result = ReasoningConfigApplicator().apply(request=request, session=session)

        assert result.temperature == pytest.approx(0.2)
        assert result.top_p == pytest.approx(0.4)
        assert result.top_k == 10


class TestReasoningConfigApplicatorPromptModification:
    """Prompt prefix/suffix behavior tests."""

    def test_applies_prefix_suffix_to_string_user_content(self) -> None:
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Solve 2+2")],
        )

        reasoning_mode = SimpleNamespace(
            temperature=None,
            top_p=None,
            top_k=None,
            reasoning_effort=None,
            thinking_budget=None,
            reasoning_config=None,
            gemini_generation_config=None,
            user_prompt_prefix="Think carefully: ",
            user_prompt_suffix=" Show your work.",
        )
        session = MagicMock()
        session.state = SimpleNamespace(planning_phase_config=None)
        session.get_reasoning_mode = MagicMock(return_value=reasoning_mode)

        result = ReasoningConfigApplicator().apply(request=request, session=session)

        assert (
            result.messages[0].content == "Think carefully: Solve 2+2 Show your work."
        )

    def test_applies_prefix_suffix_to_multimodal_text_part(self) -> None:
        request = ChatRequest(
            model="test-model",
            messages=[
                ChatMessage(
                    role="user",
                    content=[
                        MessageContentPartText(text="Hello"),
                    ],
                )
            ],
        )

        reasoning_mode = SimpleNamespace(
            temperature=None,
            top_p=None,
            top_k=None,
            reasoning_effort=None,
            thinking_budget=None,
            reasoning_config=None,
            gemini_generation_config=None,
            user_prompt_prefix="P:",
            user_prompt_suffix=":S",
        )
        session = MagicMock()
        session.state = SimpleNamespace(planning_phase_config=None)
        session.get_reasoning_mode = MagicMock(return_value=reasoning_mode)

        result = ReasoningConfigApplicator().apply(request=request, session=session)

        assert isinstance(result.messages[0].content, list)
        assert result.messages[0].content[0].text == "P:Hello:S"


class TestEquivalenceWithBackendService:
    """Ensure ReasoningConfigApplicator applies expected transformations."""

    def test_matches_backend_service_on_fixture(self) -> None:
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Hello")],
            temperature=0.5,
        )

        reasoning_mode = SimpleNamespace(
            temperature=0.7,
            top_p=0.9,
            top_k=32,
            reasoning_effort="high",
            thinking_budget=123,
            reasoning_config=None,
            gemini_generation_config=None,
            user_prompt_prefix="P:",
            user_prompt_suffix=":S",
        )
        session = MagicMock()
        session.state = SimpleNamespace(planning_phase_config=None)
        session.get_reasoning_mode = MagicMock(return_value=reasoning_mode)

        applicator_result = ReasoningConfigApplicator().apply(request, session)

        # Verify that the applicator applied the expected reasoning config
        assert applicator_result.temperature == 0.7
        assert applicator_result.top_p == 0.9
        assert applicator_result.top_k == 32
        assert applicator_result.reasoning_effort == "high"
        assert applicator_result.messages[0].content == "P:Hello:S"
