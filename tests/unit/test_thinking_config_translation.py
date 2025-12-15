"""
Test that reasoning_effort is correctly translated to Gemini's thinkingConfig.

Gemini uses thinkingBudget (integer for max tokens) not reasoning_effort (string).
Based on gemini-cli reference: dev/thrdparty/gemini-cli-new/packages/core/src/config/models.ts
"""

import pytest
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.services.translation_service import TranslationService


@pytest.fixture(autouse=True)
def isolate_test_completely():
    """Ensure complete test isolation by clearing any global state."""
    import os

    # Store original environment
    original_env = dict(os.environ)

    # Remove variables that would interfere with thinking config tests (e.g. set by CI)
    os.environ.pop("THINKING_BUDGET", None)

    yield

    # Restore original environment completely
    os.environ.clear()
    os.environ.update(original_env)


class TestThinkingConfigTranslation:
    """Test reasoning_effort -> thinkingBudget translation."""

    def test_reasoning_effort_low_maps_to_512_tokens(self) -> None:
        """Test that 'low' effort maps to 512 token budget."""
        import os

        # Clear any THINKING_BUDGET environment variable that might interfere
        original_thinking_budget = os.environ.pop("THINKING_BUDGET", None)

        try:
            service = TranslationService()

            request = CanonicalChatRequest(
                model="gemini-2.5-pro",
                messages=[ChatMessage(role="user", content="test")],
                reasoning_effort="low",
            )

            gemini_request = service.from_domain_to_gemini_request(request)

            assert "generationConfig" in gemini_request
            assert "thinkingConfig" in gemini_request["generationConfig"]

            thinking_config = gemini_request["generationConfig"]["thinkingConfig"]

            # CRITICAL: Must use thinkingBudget (int), not reasoning_effort (string)
            assert "thinkingBudget" in thinking_config
            assert thinking_config["thinkingBudget"] == 512

            # Should include thoughts in output
            assert thinking_config.get("includeThoughts") is True
        finally:
            # Restore original THINKING_BUDGET if it existed
            if original_thinking_budget is not None:
                os.environ["THINKING_BUDGET"] = original_thinking_budget

    def test_reasoning_effort_medium_maps_to_2048_tokens(self) -> None:
        """Test that 'medium' effort maps to 2048 token budget."""
        service = TranslationService()

        request = CanonicalChatRequest(
            model="gemini-2.5-pro",
            messages=[ChatMessage(role="user", content="test")],
            reasoning_effort="medium",
        )

        gemini_request = service.from_domain_to_gemini_request(request)

        thinking_config = gemini_request["generationConfig"]["thinkingConfig"]
        assert thinking_config["thinkingBudget"] == 2048
        assert thinking_config["includeThoughts"] is True

    def test_reasoning_effort_high_maps_to_dynamic(self) -> None:
        """Test that 'high' effort maps to -1 (dynamic/unlimited).

        According to gemini-cli:
        DEFAULT_THINKING_MODE = -1 (dynamic thinking)
        """
        service = TranslationService()

        request = CanonicalChatRequest(
            model="gemini-2.5-pro",
            messages=[ChatMessage(role="user", content="test")],
            reasoning_effort="high",
        )

        gemini_request = service.from_domain_to_gemini_request(request)

        thinking_config = gemini_request["generationConfig"]["thinkingConfig"]

        # -1 means dynamic/unlimited (let model decide)
        assert thinking_config["thinkingBudget"] == -1
        assert thinking_config["includeThoughts"] is True

    def test_no_reasoning_effort_no_thinking_config(self) -> None:
        """Test that without reasoning_effort, no thinkingConfig is added."""
        service = TranslationService()

        request = CanonicalChatRequest(
            model="gemini-2.5-pro",
            messages=[ChatMessage(role="user", content="test")],
            # No reasoning_effort specified
        )

        gemini_request = service.from_domain_to_gemini_request(request)

        # Should not have thinkingConfig if not requested
        assert "thinkingConfig" not in gemini_request.get("generationConfig", {})

    def test_thinking_config_structure(self) -> None:
        """Document the expected thinkingConfig structure for Gemini API."""
        # Based on gemini-cli source code
        expected_structure = {
            "thinkingBudget": -1,  # int: -1=dynamic, 0=none, >0=max tokens
            "includeThoughts": True,  # bool: include reasoning in output
        }

        # Verify structure
        assert isinstance(expected_structure["thinkingBudget"], int)
        assert isinstance(expected_structure["includeThoughts"], bool)

        # Common values for thinkingBudget
        valid_budgets = [
            -1,  # Dynamic/unlimited (DEFAULT_THINKING_MODE in gemini-cli)
            0,  # No thinking
            512,  # Low budget
            2048,  # Medium budget
            8192,  # High budget
        ]

        for budget in valid_budgets:
            assert isinstance(budget, int)


def test_cli_thinking_budget_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure THINKING_BUDGET env var overrides reasoning_effort mapping."""

    service = TranslationService()

    request = CanonicalChatRequest(
        model="gemini-2.5-pro",
        messages=[ChatMessage(role="user", content="test")],
        reasoning_effort="low",  # Would map to 512 without override
    )

    monkeypatch.setenv("THINKING_BUDGET", "8192")

    gemini_request = service.from_domain_to_gemini_request(request)

    generation_config = gemini_request.get("generationConfig", {})
    thinking_config = generation_config.get("thinkingConfig")

    assert thinking_config is not None, "Expected thinkingConfig when override is set"
    assert thinking_config["thinkingBudget"] == 8192
    assert thinking_config["includeThoughts"] is True
