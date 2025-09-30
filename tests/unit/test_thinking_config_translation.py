"""
Test that reasoning_effort is correctly translated to Gemini's thinkingConfig.

Gemini uses thinkingBudget (integer for max tokens) not reasoning_effort (string).
Based on gemini-cli reference: dev/thrdparty/gemini-cli-new/packages/core/src/config/models.ts
"""

from src.core.domain.chat import ChatRequest
from src.core.services.translation_service import TranslationService


class TestThinkingConfigTranslation:
    """Test reasoning_effort -> thinkingBudget translation."""

    def test_reasoning_effort_low_maps_to_512_tokens(self) -> None:
        """Test that 'low' effort maps to 512 token budget."""
        service = TranslationService()

        request = ChatRequest(
            model="gemini-2.5-pro",
            messages=[{"role": "user", "content": "test"}],
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

    def test_reasoning_effort_medium_maps_to_2048_tokens(self) -> None:
        """Test that 'medium' effort maps to 2048 token budget."""
        service = TranslationService()

        request = ChatRequest(
            model="gemini-2.5-pro",
            messages=[{"role": "user", "content": "test"}],
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

        request = ChatRequest(
            model="gemini-2.5-pro",
            messages=[{"role": "user", "content": "test"}],
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

        request = ChatRequest(
            model="gemini-2.5-pro",
            messages=[{"role": "user", "content": "test"}],
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


def test_thinking_config_documentation() -> None:
    """Document the thinkingConfig parameter based on gemini-cli source.

    Source: dev/thrdparty/gemini-cli-new/packages/core/src/config/models.ts

    Key findings:
    - Gemini uses thinkingBudget (integer) not reasoning_effort (string)
    - -1 = DEFAULT_THINKING_MODE (dynamic, let model decide)
    - 0 = no thinking
    - >0 = max thinking tokens
    - includeThoughts: true to include reasoning in output

    Usage in gemini-cli:
    ```typescript
    config.thinkingConfig = {
      includeThoughts: true,
      thinkingBudget: DEFAULT_THINKING_MODE,  // -1
    };
    ```
    """
    # This test documents the correct API structure
    assert True
