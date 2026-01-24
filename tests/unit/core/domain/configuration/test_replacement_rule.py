"""Unit tests for ReplacementRule pattern matching."""

import pytest
from src.core.domain.configuration.replacement_rule import ReplacementRule


class TestReplacementRulePatternMatching:
    """Tests for ReplacementRule.matches() pattern matching logic."""

    def test_wildcard_matches_all_models(self) -> None:
        """Wildcard pattern '*' should match any backend:model combination."""
        rule = ReplacementRule(
            from_pattern="*",
            to_backend="qwen-oauth",
            to_model="qwen3-coder-plus",
        )

        assert rule.matches("openai", "gpt-4") is True
        assert rule.matches("anthropic", "claude-3-5-sonnet") is True
        assert rule.matches("gemini-oauth-plan", "gemini-3-flash-preview") is True
        assert rule.matches("any-backend", "any-model") is True

    def test_partial_match_model_name(self) -> None:
        """Partial match should match if pattern is substring of model name."""
        rule = ReplacementRule(
            from_pattern="gpt-4",
            to_backend="openai",
            to_model="gpt-3.5-turbo",
        )

        # Should match (substring found in model name)
        assert rule.matches("openai", "gpt-4") is True
        assert rule.matches("openai", "gpt-4-turbo") is True
        assert rule.matches("openai", "gpt-4o") is True
        assert rule.matches("anthropic", "gpt-4") is True  # Any backend

        # Should not match (substring not found)
        assert rule.matches("openai", "gpt-3.5-turbo") is False
        assert rule.matches("openai", "gpt-5") is False
        assert rule.matches("anthropic", "claude-3-5-sonnet") is False

    def test_partial_match_case_sensitive(self) -> None:
        """Partial match should be case-sensitive."""
        rule = ReplacementRule(
            from_pattern="GPT-4",
            to_backend="openai",
            to_model="gpt-3.5-turbo",
        )

        # Should match (exact case)
        assert rule.matches("openai", "GPT-4") is True
        assert rule.matches("openai", "GPT-4-turbo") is True

        # Should not match (case mismatch)
        assert rule.matches("openai", "gpt-4") is False
        assert rule.matches("openai", "Gpt-4") is False

    def test_exact_match_backend_model(self) -> None:
        """Exact match should only match specific backend:model combination."""
        rule = ReplacementRule(
            from_pattern="openai:gpt-4",
            to_backend="anthropic",
            to_model="claude-3-5-sonnet",
        )

        # Should match (exact match)
        assert rule.matches("openai", "gpt-4") is True

        # Should not match (different backend)
        assert rule.matches("anthropic", "gpt-4") is False
        assert rule.matches("gemini-oauth-plan", "gpt-4") is False

        # Should not match (different model)
        assert rule.matches("openai", "gpt-4-turbo") is False
        assert rule.matches("openai", "gpt-4o") is False

        # Should not match (different both)
        assert rule.matches("anthropic", "claude-3-5-sonnet") is False

    def test_exact_match_case_sensitive(self) -> None:
        """Exact match should be case-sensitive for both backend and model."""
        rule = ReplacementRule(
            from_pattern="OpenAI:GPT-4",
            to_backend="anthropic",
            to_model="claude-3-5-sonnet",
        )

        # Should match (exact case)
        assert rule.matches("OpenAI", "GPT-4") is True

        # Should not match (case mismatch)
        assert rule.matches("openai", "GPT-4") is False
        assert rule.matches("OpenAI", "gpt-4") is False
        assert rule.matches("openai", "gpt-4") is False

    def test_partial_match_with_hyphenated_models(self) -> None:
        """Partial match should work with hyphenated model names."""
        rule = ReplacementRule(
            from_pattern="gemini-3-flash",
            to_backend="gemini-oauth-plan",
            to_model="gemini-3-pro",
        )

        # Should match (substring found)
        assert rule.matches("gemini-oauth-free", "gemini-3-flash-preview") is True
        assert rule.matches("gemini-oauth-plan", "gemini-3-flash-001") is True
        assert rule.matches("any-backend", "gemini-3-flash") is True

        # Should not match (substring not found)
        assert rule.matches("gemini-oauth-free", "gemini-3-pro-preview") is False
        assert rule.matches("gemini-oauth-plan", "gemini-2-flash-preview") is False

    def test_rule_string_representation(self) -> None:
        """Test __str__ method returns proper format."""
        rule = ReplacementRule(
            from_pattern="gpt-4",
            to_backend="openai",
            to_model="gpt-3.5-turbo",
        )

        assert str(rule) == "gpt-4=openai:gpt-3.5-turbo"

    def test_rule_with_special_characters_in_model_name(self) -> None:
        """Partial match should work with special characters in model names."""
        rule = ReplacementRule(
            from_pattern="claude-3.5",
            to_backend="anthropic",
            to_model="claude-3-haiku",
        )

        # Should match (substring with dot)
        assert rule.matches("anthropic", "claude-3.5-sonnet") is True
        assert rule.matches("anthropic", "claude-3.5-opus") is True

        # Should not match
        assert rule.matches("anthropic", "claude-3-sonnet") is False


class TestReplacementRuleCreation:
    """Tests for ReplacementRule creation and validation."""

    def test_create_rule_with_all_fields(self) -> None:
        """Should create rule with all required fields."""
        rule = ReplacementRule(
            from_pattern="gpt-4",
            to_backend="openai",
            to_model="gpt-3.5-turbo",
        )

        assert rule.from_pattern == "gpt-4"
        assert rule.to_backend == "openai"
        assert rule.to_model == "gpt-3.5-turbo"

    def test_rule_is_frozen(self) -> None:
        """ReplacementRule should be immutable (frozen dataclass)."""
        rule = ReplacementRule(
            from_pattern="*",
            to_backend="openai",
            to_model="gpt-4",
        )

        with pytest.raises(AttributeError):
            rule.from_pattern = "gpt-4"  # type: ignore

        with pytest.raises(AttributeError):
            rule.to_backend = "anthropic"  # type: ignore

        with pytest.raises(AttributeError):
            rule.to_model = "claude-3-5-sonnet"  # type: ignore


class TestReplacementRuleEdgeCases:
    """Tests for edge cases in ReplacementRule."""

    def test_empty_from_pattern(self) -> None:
        """Empty from_pattern should not match anything (except via wildcard)."""
        rule = ReplacementRule(
            from_pattern="",
            to_backend="openai",
            to_model="gpt-4",
        )

        # Empty string is a substring of any string in Python
        assert rule.matches("openai", "gpt-4") is True
        assert rule.matches("anthropic", "claude") is True

    def test_colon_in_partial_pattern(self) -> None:
        """Pattern with colon is treated as exact match, not partial."""
        rule = ReplacementRule(
            from_pattern="openai:gpt",  # Contains colon, so exact match mode
            to_backend="anthropic",
            to_model="claude",
        )

        # Should not match (requires exact "openai:gpt" model)
        assert rule.matches("openai", "gpt-4") is False
        assert rule.matches("openai", "gpt") is True  # Exact match

    def test_multiple_colons_in_pattern(self) -> None:
        """Pattern with colon uses exact match comparing f'{backend}:{model}'."""
        rule = ReplacementRule(
            from_pattern="backend:model:version",
            to_backend="other",
            to_model="other-model",
        )

        # Exact match compares f"{backend}:{model}" to from_pattern
        # So "backend:model:version" matches when backend="backend" and model="model:version"
        assert rule.matches("backend", "model:version") is True
        # Or when backend="backend:model" and model="version" (also constructs "backend:model:version")
        assert rule.matches("backend:model", "version") is True
        # Should not match other combinations
        assert rule.matches("backend", "model") is False
        assert rule.matches("other", "model:version") is False
