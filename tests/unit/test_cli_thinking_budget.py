"""
Test that --thinking-budget CLI flag correctly sets the thinkingBudget parameter.
"""

import os

from src.core.cli import apply_cli_args, parse_cli_args
from src.core.domain.chat import ChatRequest
from src.core.services.translation_service import TranslationService


class TestCLIThinkingBudget:
    """Test --thinking-budget CLI flag."""

    def test_cli_thinking_budget_is_parsed(self) -> None:
        """Test that --thinking-budget flag is properly parsed."""
        args = parse_cli_args(["--thinking-budget", "32768"])

        assert hasattr(args, "thinking_budget")
        assert args.thinking_budget == 32768

    def test_cli_thinking_budget_sets_env_var(self) -> None:
        """Test that --thinking-budget sets THINKING_BUDGET env var."""
        # Clean environment first
        if "THINKING_BUDGET" in os.environ:
            del os.environ["THINKING_BUDGET"]

        args = parse_cli_args(["--thinking-budget", "32768"])
        _ = apply_cli_args(args)

        assert os.environ.get("THINKING_BUDGET") == "32768"

        # Cleanup
        if "THINKING_BUDGET" in os.environ:
            del os.environ["THINKING_BUDGET"]

    def test_translation_uses_cli_override(self) -> None:
        """Test that translation service picks up CLI override."""
        # Set environment variable as CLI would
        os.environ["THINKING_BUDGET"] = "32768"

        try:
            service = TranslationService()

            request = ChatRequest(
                model="gemini-2.5-pro",
                messages=[{"role": "user", "content": "test"}],
                # Even if reasoning_effort is set, CLI should override
                reasoning_effort="low",
            )

            gemini_request = service.from_domain_to_gemini_request(request)

            thinking_config = gemini_request["generationConfig"]["thinkingConfig"]

            # Should use CLI value (32768), not the "low" mapping (512)
            assert thinking_config["thinkingBudget"] == 32768
            assert thinking_config["includeThoughts"] is True

        finally:
            # Cleanup
            if "THINKING_BUDGET" in os.environ:
                del os.environ["THINKING_BUDGET"]

    def test_cli_override_precedence(self) -> None:
        """Test that CLI override takes precedence over reasoning_effort."""
        os.environ["THINKING_BUDGET"] = "16384"

        try:
            service = TranslationService()

            # Request with high effort (would normally be -1)
            request = ChatRequest(
                model="gemini-2.5-pro",
                messages=[{"role": "user", "content": "test"}],
                reasoning_effort="high",
            )

            gemini_request = service.from_domain_to_gemini_request(request)
            thinking_config = gemini_request["generationConfig"]["thinkingConfig"]

            # CLI value should win
            assert thinking_config["thinkingBudget"] == 16384

        finally:
            if "THINKING_BUDGET" in os.environ:
                del os.environ["THINKING_BUDGET"]

    def test_no_cli_override_uses_reasoning_effort(self) -> None:
        """Test that without CLI flag, reasoning_effort works normally."""
        # Ensure no CLI override
        if "THINKING_BUDGET" in os.environ:
            del os.environ["THINKING_BUDGET"]

        service = TranslationService()

        request = ChatRequest(
            model="gemini-2.5-pro",
            messages=[{"role": "user", "content": "test"}],
            reasoning_effort="low",
        )

        gemini_request = service.from_domain_to_gemini_request(request)
        thinking_config = gemini_request["generationConfig"]["thinkingConfig"]

        # Should use the effort mapping (512 for "low")
        assert thinking_config["thinkingBudget"] == 512

    def test_dynamic_thinking_via_cli(self) -> None:
        """Test setting -1 (dynamic/unlimited) via CLI."""
        os.environ["THINKING_BUDGET"] = "-1"

        try:
            service = TranslationService()

            request = ChatRequest(
                model="gemini-2.5-pro", messages=[{"role": "user", "content": "test"}]
            )

            gemini_request = service.from_domain_to_gemini_request(request)
            thinking_config = gemini_request["generationConfig"]["thinkingConfig"]

            assert thinking_config["thinkingBudget"] == -1

        finally:
            if "THINKING_BUDGET" in os.environ:
                del os.environ["THINKING_BUDGET"]

    def test_zero_thinking_via_cli(self) -> None:
        """Test disabling thinking (0) via CLI."""
        os.environ["THINKING_BUDGET"] = "0"

        try:
            service = TranslationService()

            request = ChatRequest(
                model="gemini-2.5-pro", messages=[{"role": "user", "content": "test"}]
            )

            gemini_request = service.from_domain_to_gemini_request(request)
            thinking_config = gemini_request["generationConfig"]["thinkingConfig"]

            assert thinking_config["thinkingBudget"] == 0

        finally:
            if "THINKING_BUDGET" in os.environ:
                del os.environ["THINKING_BUDGET"]


def test_cli_thinking_budget_documentation() -> None:
    """Document the --thinking-budget CLI flag usage.
    
    Usage:
    ------
    ./.venv/Scripts/python.exe -m src.core.cli \
      --host 127.0.0.1 --port 8000 \
      --disable-auth \
      --default-backend gemini-cli-oauth-personal \
      --static-route gemini-cli-oauth-personal:gemini-2.5-pro \
      --thinking-budget 32768
    
    This sets the thinkingBudget to 32768 tokens for ALL requests,
    overriding any reasoning_effort values in individual requests.
    
    Special values:
    - -1 = dynamic/unlimited (let model decide)
    - 0 = disable thinking/reasoning
    - >0 = max thinking tokens (e.g., 32768)
    """
    # This test documents the feature
    assert True
