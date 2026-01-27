"""Unit tests for ReplacementConfig validation improvements."""

import pytest
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.configuration.replacement_rule import ReplacementRule


class TestWildcardExclusivityValidation:
    """Tests for wildcard exclusivity validation."""

    def test_single_wildcard_rule_is_valid(self) -> None:
        """A single wildcard rule by itself should be valid."""
        rule = ReplacementRule(
            from_pattern="*", to_backend="qwen-oauth", to_model="qwen3-coder-plus"
        )
        config = ReplacementConfig(
            enabled=True,
            probability=0.5,
            replacement_rules=[rule],
            turn_count=1,
        )
        # Should not raise
        config.validate_config()

    def test_wildcard_with_other_rules_is_invalid(self) -> None:
        """Wildcard rule combined with other rules should be invalid."""
        rules = [
            ReplacementRule(
                from_pattern="*", to_backend="qwen-oauth", to_model="qwen3-coder-plus"
            ),
            ReplacementRule(
                from_pattern="gpt-4", to_backend="openai", to_model="gpt-3.5-turbo"
            ),
        ]

        with pytest.raises(
            ValueError, match="Wildcard.*cannot be combined with other rules"
        ):
            ReplacementConfig(
                enabled=True,
                probability=0.5,
                replacement_rules=rules,
                turn_count=1,
            )

    def test_multiple_specific_rules_without_wildcard_is_valid(self) -> None:
        """Multiple specific rules without wildcard should be valid."""
        rules = [
            ReplacementRule(
                from_pattern="openai:gpt-4",
                to_backend="anthropic",
                to_model="claude-3-5-sonnet",
            ),
            ReplacementRule(
                from_pattern="gpt-4", to_backend="openai", to_model="gpt-3.5-turbo"
            ),
            ReplacementRule(
                from_pattern="gemini-3-flash-preview",
                to_backend="gemini-oauth-plan",
                to_model="gemini-3-pro-preview",
            ),
        ]

        config = ReplacementConfig(
            enabled=True,
            probability=0.5,
            replacement_rules=rules,
            turn_count=1,
        )
        # Should not raise
        config.validate_config()

    def test_wildcard_at_end_with_other_rules_is_invalid(self) -> None:
        """Wildcard at the end is also invalid when combined with other rules."""
        rules = [
            ReplacementRule(
                from_pattern="gpt-4", to_backend="openai", to_model="gpt-3.5-turbo"
            ),
            ReplacementRule(
                from_pattern="*", to_backend="qwen-oauth", to_model="qwen3-coder-plus"
            ),
        ]

        with pytest.raises(
            ValueError, match="Wildcard.*cannot be combined with other rules"
        ):
            ReplacementConfig(
                enabled=True,
                probability=0.5,
                replacement_rules=rules,
                turn_count=1,
            )


class TestWildcardReplacementTargetValidation:
    """Tests for wildcard in replacement target validation."""

    def test_wildcard_in_to_backend_is_invalid(self) -> None:
        """Wildcard as replacement backend should be invalid."""
        rule = ReplacementRule(
            from_pattern="gpt-4", to_backend="*", to_model="gpt-3.5-turbo"
        )

        with pytest.raises(ValueError, match="Replacement target cannot use wildcard"):
            ReplacementConfig(
                enabled=True,
                probability=0.5,
                replacement_rules=[rule],
                turn_count=1,
            )

    def test_wildcard_in_to_model_is_invalid(self) -> None:
        """Wildcard as replacement model should be invalid."""
        rule = ReplacementRule(from_pattern="gpt-4", to_backend="openai", to_model="*")

        with pytest.raises(ValueError, match="Replacement target cannot use wildcard"):
            ReplacementConfig(
                enabled=True,
                probability=0.5,
                replacement_rules=[rule],
                turn_count=1,
            )

    def test_wildcard_in_both_to_parts_is_invalid(self) -> None:
        """Wildcard in both backend and model should be invalid."""
        rule = ReplacementRule(from_pattern="gpt-4", to_backend="*", to_model="*")

        with pytest.raises(ValueError, match="Replacement target cannot use wildcard"):
            ReplacementConfig(
                enabled=True,
                probability=0.5,
                replacement_rules=[rule],
                turn_count=1,
            )

    def test_wildcard_from_to_concrete_backend_model_is_valid(self) -> None:
        """Wildcard in from_pattern to concrete backend:model should be valid."""
        rule = ReplacementRule(
            from_pattern="*", to_backend="qwen-oauth", to_model="qwen3-coder-plus"
        )

        config = ReplacementConfig(
            enabled=True,
            probability=0.5,
            replacement_rules=[rule],
            turn_count=1,
        )
        # Should not raise
        config.validate_config()


class TestCombinedValidationScenarios:
    """Tests for combined validation scenarios."""

    def test_wildcard_from_and_to_is_invalid(self) -> None:
        """Wildcard in both from and to should be invalid."""
        rule = ReplacementRule(from_pattern="*", to_backend="*", to_model="*")

        with pytest.raises(ValueError, match="Replacement target cannot use wildcard"):
            ReplacementConfig(
                enabled=True,
                probability=0.5,
                replacement_rules=[rule],
                turn_count=1,
            )

    def test_wildcard_exclusivity_checked_before_target_validation(self) -> None:
        """Wildcard exclusivity should be checked first."""
        rules = [
            ReplacementRule(
                from_pattern="*", to_backend="qwen-oauth", to_model="qwen3-coder-plus"
            ),
            ReplacementRule(
                from_pattern="gpt-4", to_backend="openai", to_model="gpt-3.5-turbo"
            ),
        ]

        # Should fail on wildcard exclusivity, not target validation
        with pytest.raises(
            ValueError, match="Wildcard.*cannot be combined with other rules"
        ):
            ReplacementConfig(
                enabled=True,
                probability=0.5,
                replacement_rules=rules,
                turn_count=1,
            )
