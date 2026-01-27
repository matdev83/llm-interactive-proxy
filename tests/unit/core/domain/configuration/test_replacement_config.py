"""Unit tests for ReplacementConfig."""

import pytest
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.configuration.replacement_rule import ReplacementRule


class TestReplacementConfigValidation:
    """Tests for ReplacementConfig validation logic."""

    def test_disabled_config_passes_validation(self) -> None:
        """Disabled replacement config should pass validation even without rules."""
        config = ReplacementConfig(
            enabled=False,
            probability=0.0,
            replacement_rules=[],
            turn_count=1,
        )
        # Should not raise
        config.validate_config()

    def test_enabled_requires_rules(self) -> None:
        """Enabled replacement config must have at least one rule."""
        with pytest.raises(
            ValueError, match="replacement_rules must be provided when enabled"
        ):
            ReplacementConfig(
                enabled=True,
                probability=0.3,
                replacement_rules=[],
                turn_count=1,
            )

    def test_probability_must_be_in_range(self) -> None:
        """Probability must be between 0.0 and 1.0."""
        rule = ReplacementRule(from_pattern="*", to_backend="openai", to_model="gpt-4")

        # Too low
        with pytest.raises(ValueError, match="replacement_probability must be between"):
            ReplacementConfig(
                enabled=True,
                probability=-0.1,
                replacement_rules=[rule],
                turn_count=1,
            )

        # Too high
        with pytest.raises(ValueError, match="replacement_probability must be between"):
            ReplacementConfig(
                enabled=True,
                probability=1.5,
                replacement_rules=[rule],
                turn_count=1,
            )

        # Valid boundaries
        config_zero = ReplacementConfig(
            enabled=True,
            probability=0.0,
            replacement_rules=[rule],
            turn_count=1,
        )
        config_zero.validate_config()

        config_one = ReplacementConfig(
            enabled=True,
            probability=1.0,
            replacement_rules=[rule],
            turn_count=1,
        )
        config_one.validate_config()

    def test_turn_count_must_be_positive(self) -> None:
        """Turn count must be at least 1."""
        rule = ReplacementRule(from_pattern="*", to_backend="openai", to_model="gpt-4")

        with pytest.raises(
            ValueError, match="replacement_turn_count must be at least 1"
        ):
            ReplacementConfig(
                enabled=True,
                probability=0.3,
                replacement_rules=[rule],
                turn_count=0,
            )

        with pytest.raises(
            ValueError, match="replacement_turn_count must be at least 1"
        ):
            ReplacementConfig(
                enabled=True,
                probability=0.3,
                replacement_rules=[rule],
                turn_count=-1,
            )

    def test_rule_must_have_to_backend_and_to_model(self) -> None:
        """Each rule must have non-empty to_backend and to_model."""
        # Empty to_backend
        rule_empty_backend = ReplacementRule(
            from_pattern="*", to_backend="", to_model="gpt-4"
        )
        with pytest.raises(
            ValueError, match="to_backend and to_model must be provided"
        ):
            ReplacementConfig(
                enabled=True,
                probability=0.3,
                replacement_rules=[rule_empty_backend],
                turn_count=1,
            )

        # Empty to_model
        rule_empty_model = ReplacementRule(
            from_pattern="*", to_backend="openai", to_model=""
        )
        with pytest.raises(
            ValueError, match="to_backend and to_model must be provided"
        ):
            ReplacementConfig(
                enabled=True,
                probability=0.3,
                replacement_rules=[rule_empty_model],
                turn_count=1,
            )


class TestReplacementConfigFindMatchingRule:
    """Tests for ReplacementConfig.find_matching_rule()."""

    def test_find_exact_match_rule(self) -> None:
        """Should find exact match rule when it exists."""
        rules = [
            ReplacementRule(
                from_pattern="openai:gpt-4",
                to_backend="anthropic",
                to_model="claude-3-5-sonnet",
            ),
            ReplacementRule(
                from_pattern="gpt-4", to_backend="openai", to_model="gpt-3.5-turbo"
            ),
        ]
        config = ReplacementConfig(
            enabled=True,
            probability=0.3,
            replacement_rules=rules,
            turn_count=1,
        )

        matched = config.find_matching_rule("openai", "gpt-4")
        assert matched is not None
        assert matched.from_pattern == "openai:gpt-4"
        assert matched.to_backend == "anthropic"
        assert matched.to_model == "claude-3-5-sonnet"

    def test_find_partial_match_rule(self) -> None:
        """Should find partial match rule when pattern is in model name."""
        rules = [
            ReplacementRule(
                from_pattern="gpt-4",
                to_backend="openai",
                to_model="gpt-3.5-turbo",
            ),
            ReplacementRule(
                from_pattern="claude", to_backend="anthropic", to_model="claude-3-haiku"
            ),
        ]
        config = ReplacementConfig(
            enabled=True,
            probability=0.3,
            replacement_rules=rules,
            turn_count=1,
        )

        matched = config.find_matching_rule("openai", "gpt-4-turbo")
        assert matched is not None
        assert matched.from_pattern == "gpt-4"
        assert matched.to_backend == "openai"
        assert matched.to_model == "gpt-3.5-turbo"

    def test_find_wildcard_rule(self) -> None:
        """Should find wildcard rule when it's the only rule (wildcard exclusivity)."""
        rules = [
            ReplacementRule(
                from_pattern="*", to_backend="qwen-oauth", to_model="qwen3-coder-plus"
            ),
        ]
        config = ReplacementConfig(
            enabled=True,
            probability=0.3,
            replacement_rules=rules,
            turn_count=1,
        )

        matched = config.find_matching_rule("anthropic", "claude-3-5-sonnet")
        assert matched is not None
        assert matched.from_pattern == "*"
        assert matched.to_backend == "qwen-oauth"
        assert matched.to_model == "qwen3-coder-plus"

    def test_first_match_wins(self) -> None:
        """Should return first matching rule when multiple rules match."""
        rules = [
            ReplacementRule(
                from_pattern="openai:gpt-4",
                to_backend="first",
                to_model="first-model",
            ),
            ReplacementRule(
                from_pattern="gpt-4", to_backend="second", to_model="second-model"
            ),
            ReplacementRule(
                from_pattern="claude", to_backend="third", to_model="third-model"
            ),
        ]
        config = ReplacementConfig(
            enabled=True,
            probability=0.3,
            replacement_rules=rules,
            turn_count=1,
        )

        # Exact match should win
        matched = config.find_matching_rule("openai", "gpt-4")
        assert matched is not None
        assert matched.to_backend == "first"

        # Partial match should win when exact doesn't match
        matched = config.find_matching_rule("anthropic", "gpt-4-turbo")
        assert matched is not None
        assert matched.to_backend == "second"

    def test_no_matching_rule_returns_none(self) -> None:
        """Should return None when no rule matches."""
        rules = [
            ReplacementRule(
                from_pattern="gpt-4",
                to_backend="openai",
                to_model="gpt-3.5-turbo",
            ),
            ReplacementRule(
                from_pattern="claude",
                to_backend="anthropic",
                to_model="claude-3-haiku",
            ),
        ]
        config = ReplacementConfig(
            enabled=True,
            probability=0.3,
            replacement_rules=rules,
            turn_count=1,
        )

        matched = config.find_matching_rule(
            "gemini-oauth-free", "gemini-3-flash-preview"
        )
        assert matched is None

    def test_gemini_flash_to_pro_example(self) -> None:
        """Test the user's specific example: gemini-3-flash-preview replacement."""
        rule = ReplacementRule(
            from_pattern="gemini-3-flash-preview",
            to_backend="gemini-oauth-plan",
            to_model="gemini-3-pro-preview",
        )
        config = ReplacementConfig(
            enabled=True,
            probability=0.3,
            replacement_rules=[rule],
            turn_count=1,
        )

        # Should match regardless of backend
        matched = config.find_matching_rule(
            "some-backend-name", "gemini-3-flash-preview"
        )
        assert matched is not None
        assert matched.to_backend == "gemini-oauth-plan"
        assert matched.to_model == "gemini-3-pro-preview"

        # Should also match with different backend
        matched = config.find_matching_rule(
            "gemini-oauth-free", "gemini-3-flash-preview"
        )
        assert matched is not None
        assert matched.to_backend == "gemini-oauth-plan"
        assert matched.to_model == "gemini-3-pro-preview"


class TestReplacementConfigLegacyMigration:
    """Tests for legacy backend_model format migration."""

    def test_migrate_legacy_backend_model_to_wildcard_rule(self) -> None:
        """Legacy backend_model should be migrated to wildcard replacement rule."""
        config = ReplacementConfig(
            enabled=True,
            probability=0.3,
            backend_model="qwen-oauth:qwen3-coder-plus",
            replacement_rules=[],
            turn_count=3,
        )

        assert len(config.replacement_rules) == 1
        rule = config.replacement_rules[0]
        assert rule.from_pattern == "*"
        assert rule.to_backend == "qwen-oauth"
        assert rule.to_model == "qwen3-coder-plus"

    def test_replacement_rules_take_precedence_over_legacy(self) -> None:
        """If both backend_model and replacement_rules are set, use replacement_rules."""
        rule = ReplacementRule(
            from_pattern="gpt-4", to_backend="openai", to_model="gpt-3.5-turbo"
        )
        config = ReplacementConfig(
            enabled=True,
            probability=0.3,
            backend_model="qwen-oauth:qwen3-coder-plus",  # Should be ignored
            replacement_rules=[rule],
            turn_count=1,
        )

        # Should only have the explicit rule, not the migrated one
        assert len(config.replacement_rules) == 1
        assert config.replacement_rules[0].from_pattern == "gpt-4"

    def test_invalid_legacy_backend_model_skipped(self) -> None:
        """Invalid legacy backend_model should be skipped and caught by validation."""
        # Migration should skip invalid format, and validation should fail during construction
        with pytest.raises(ValueError, match="replacement_rules must be provided"):
            ReplacementConfig(
                enabled=True,
                probability=0.3,
                backend_model="invalid-no-colon",
                replacement_rules=[],
                turn_count=1,
            )


class TestReplacementConfigMultipleRules:
    """Tests for configurations with multiple replacement rules."""

    def test_config_with_multiple_rules_validates(self) -> None:
        """Config with multiple valid rules (without wildcard) should pass validation."""
        rules = [
            ReplacementRule(
                from_pattern="openai:gpt-4",
                to_backend="anthropic",
                to_model="claude-3-5-sonnet",
            ),
            ReplacementRule(
                from_pattern="gpt-4",
                to_backend="openai",
                to_model="gpt-3.5-turbo",
            ),
            ReplacementRule(
                from_pattern="gemini-3-flash-preview",
                to_backend="gemini-oauth-plan",
                to_model="gemini-3-pro-preview",
            ),
        ]

        config = ReplacementConfig(
            enabled=True,
            probability=0.3,
            replacement_rules=rules,
            turn_count=3,
        )

        # Should not raise
        config.validate_config()
        assert len(config.replacement_rules) == 3

    def test_serialization_with_multiple_rules(self) -> None:
        """Config with multiple rules should serialize/deserialize correctly."""
        rules = [
            ReplacementRule(
                from_pattern="gpt-4", to_backend="openai", to_model="gpt-3.5-turbo"
            ),
            ReplacementRule(
                from_pattern="claude", to_backend="anthropic", to_model="claude-3-haiku"
            ),
        ]

        config = ReplacementConfig(
            enabled=True,
            probability=0.5,
            replacement_rules=rules,
            turn_count=2,
        )

        # Serialize to dict
        data = config.model_dump()
        assert len(data["replacement_rules"]) == 2
        assert data["probability"] == 0.5
        assert data["turn_count"] == 2

        # Deserialize from dict
        config2 = ReplacementConfig.model_validate(data)
        assert config2.enabled is True
        assert config2.probability == 0.5
        assert len(config2.replacement_rules) == 2
        assert config2.replacement_rules[0].from_pattern == "gpt-4"
        assert config2.replacement_rules[1].from_pattern == "claude"
