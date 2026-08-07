"""Unit tests for ModelAliasResolver.

Tests regex pattern matching, capture group expansion,
invalid pattern handling, and equivalence with BackendService._apply_model_aliases.
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock

from src.core.services.model_alias_resolver import ModelAliasResolver


def mock_alias_rule(pattern: str | None, replacement: str | None) -> MagicMock:
    """Create a mock alias rule."""
    rule = MagicMock()
    rule.pattern = pattern
    rule.replacement = replacement
    return rule


def mock_config_with_aliases(aliases: list) -> MagicMock:
    """Create a mock config with model aliases."""
    config = MagicMock()
    config.model_aliases = aliases
    return config


class TestResolveMethod:
    """Tests for resolve method."""

    def test_returns_original_when_no_config(self) -> None:
        """Should return original model when config is None."""
        resolver = ModelAliasResolver(config=None)

        result = resolver.resolve("gpt-4o")

        assert result == "gpt-4o"

    def test_returns_original_when_no_aliases(self) -> None:
        """Should return original model when no aliases configured."""
        config = mock_config_with_aliases([])
        resolver = ModelAliasResolver(config=config)

        result = resolver.resolve("claude-3")

        assert result == "claude-3"

    def test_simple_pattern_replacement(self) -> None:
        """Should apply simple pattern replacement."""
        config = mock_config_with_aliases(
            [mock_alias_rule("^gpt-4o$", "openai:gpt-4o")]
        )
        resolver = ModelAliasResolver(config=config)

        result = resolver.resolve("gpt-4o")

        assert result == "openai:gpt-4o"

    def test_regex_pattern_matching(self) -> None:
        """Should match regex patterns correctly."""
        config = mock_config_with_aliases(
            [mock_alias_rule("^claude-.*$", "anthropic:claude")]
        )
        resolver = ModelAliasResolver(config=config)

        assert resolver.resolve("claude-3-sonnet") == "anthropic:claude"
        assert resolver.resolve("claude-opus") == "anthropic:claude"

    def test_non_matching_pattern_returns_original(self) -> None:
        """Should return original when pattern doesn't match."""
        config = mock_config_with_aliases([mock_alias_rule("^gpt-.*$", "openai:gpt")])
        resolver = ModelAliasResolver(config=config)

        result = resolver.resolve("claude-3")

        assert result == "claude-3"


class TestCaptureGroupExpansion:
    """Tests for capture group expansion in replacements."""

    def test_single_capture_group(self) -> None:
        """Should expand single capture group correctly."""
        config = mock_config_with_aliases(
            [mock_alias_rule("^gpt-(.*)", "openai:gpt-\\1")]
        )
        resolver = ModelAliasResolver(config=config)

        result = resolver.resolve("gpt-4o-mini")

        assert result == "openai:gpt-4o-mini"

    def test_multiple_capture_groups(self) -> None:
        """Should expand multiple capture groups correctly."""
        config = mock_config_with_aliases(
            [mock_alias_rule("^(.*)-model-(.*)$", "\\1-new-\\2")]
        )
        resolver = ModelAliasResolver(config=config)

        result = resolver.resolve("my-model-v2")

        assert result == "my-new-v2"

    def test_named_capture_groups(self) -> None:
        """Should expand named capture groups correctly."""
        config = mock_config_with_aliases(
            [
                mock_alias_rule(
                    "^(?P<provider>\\w+):(?P<model>\\w+)$", "\\g<model>@\\g<provider>"
                )
            ]
        )
        resolver = ModelAliasResolver(config=config)

        result = resolver.resolve("openai:gpt4")

        assert result == "gpt4@openai"


class TestFirstMatchWins:
    """Tests for first-match-wins behavior."""

    def test_first_matching_rule_applied(self) -> None:
        """Should apply first matching rule only."""
        config = mock_config_with_aliases(
            [
                mock_alias_rule("^gpt-4o$", "first-match"),
                mock_alias_rule("^gpt-4o$", "second-match"),
                mock_alias_rule("^gpt-.*$", "third-match"),
            ]
        )
        resolver = ModelAliasResolver(config=config)

        result = resolver.resolve("gpt-4o")

        assert result == "first-match"

    def test_earlier_non_matching_rules_skipped(self) -> None:
        """Should skip non-matching rules and apply first match."""
        config = mock_config_with_aliases(
            [
                mock_alias_rule("^claude-.*$", "claude-match"),
                mock_alias_rule("^gpt-.*$", "gpt-match"),
            ]
        )
        resolver = ModelAliasResolver(config=config)

        result = resolver.resolve("gpt-4o")

        assert result == "gpt-match"


class TestInvalidPatternHandling:
    """Tests for handling invalid patterns gracefully."""

    def test_invalid_regex_skipped(self) -> None:
        """Should skip invalid regex patterns without throwing."""
        config = mock_config_with_aliases(
            [
                mock_alias_rule("[invalid(regex", "replacement"),
                mock_alias_rule("^valid-.*$", "valid-replacement"),
            ]
        )
        resolver = ModelAliasResolver(config=config)

        # Invalid regex skipped, valid one should match
        result = resolver.resolve("valid-model")
        assert result == "valid-replacement"

        # Invalid regex skipped, no match returns original
        result = resolver.resolve("other-model")
        assert result == "other-model"

    def test_none_pattern_skipped(self) -> None:
        """Should skip aliases with None pattern."""
        config = mock_config_with_aliases(
            [
                mock_alias_rule(None, "replacement"),
                mock_alias_rule("^model$", "valid"),
            ]
        )
        resolver = ModelAliasResolver(config=config)

        result = resolver.resolve("model")

        assert result == "valid"

    def test_none_replacement_skipped(self) -> None:
        """Should skip aliases with None replacement."""
        config = mock_config_with_aliases(
            [
                mock_alias_rule("^model$", None),
                mock_alias_rule("^model$", "valid"),
            ]
        )
        resolver = ModelAliasResolver(config=config)

        result = resolver.resolve("model")

        assert result == "valid"

    def test_empty_pattern_skipped(self) -> None:
        """Should skip aliases with empty pattern."""
        config = mock_config_with_aliases(
            [
                mock_alias_rule("", "replacement"),
            ]
        )
        resolver = ModelAliasResolver(config=config)

        result = resolver.resolve("model")

        # Empty string pattern doesn't match (need at least one char)
        assert result == "model"

    def test_attribute_error_skipped(self) -> None:
        """Should skip aliases that raise AttributeError."""
        bad_alias = MagicMock()
        type(bad_alias).pattern = property(
            lambda self: (_ for _ in ()).throw(AttributeError("mock"))
        )

        config = mock_config_with_aliases([bad_alias])
        resolver = ModelAliasResolver(config=config)

        # Should not raise
        result = resolver.resolve("model")
        assert result == "model"


class TestMockConfigHandling:
    """Tests for handling mock/invalid config objects."""

    def test_non_iterable_model_aliases_handled(self) -> None:
        """Should handle non-iterable model_aliases gracefully."""
        config = MagicMock()
        config.model_aliases = 12345  # Not iterable

        resolver = ModelAliasResolver(config=config)

        result = resolver.resolve("model")

        assert result == "model"

    def test_missing_model_aliases_attribute_handled(self) -> None:
        """Should handle missing model_aliases attribute."""
        config = MagicMock(spec=[])  # No attributes

        resolver = ModelAliasResolver(config=config)

        result = resolver.resolve("model")

        assert result == "model"


class TestEquivalenceWithBackendService:
    """Integration tests verifying BackendService delegates correctly to ModelAliasResolver.

    After Phase 4 refactoring, BackendService delegates model alias resolution to
    ModelAliasResolver. These tests verify that the delegation works correctly
    and produces equivalent results.
    """

    def test_backend_service_delegates_to_model_alias_resolver(self) -> None:
        """Test that BackendService._apply_model_aliases delegates to ModelAliasResolver."""
        from src.core.config.app_config import (
            AppConfig,
            BackendSettings,
            ModelAliasRule,
        )
        from src.core.services.backend_service import BackendService

        config = AppConfig(
            backends=BackendSettings(default_backend="openai"),
            model_aliases=[
                ModelAliasRule(
                    pattern="^claude-3-sonnet-20240229$",
                    replacement="gemini-oauth-plan:gemini-1.5-flash",
                ),
            ],
        )

        # Create a ModelAliasResolver to track calls
        resolver = ModelAliasResolver(config=config)

        # Create BackendService with minimal mocks and inject our resolver
        backend_service = BackendService(
            factory=Mock(),
            rate_limiter=Mock(),
            config=config,
            session_service=Mock(),
            app_state=Mock(),
            backend_config_provider=Mock(),
            stream_formatting_service=Mock(),
            usage_tracking_wrapper=Mock(),
            model_alias_resolver=resolver,  # Inject our resolver
            exception_normalizer=Mock(),
            backend_lifecycle_manager=Mock(),
            planning_phase_manager=Mock(),
            reasoning_config_applicator=Mock(),
            uri_parameter_applicator=Mock(),
            stream_session_id_resolver=Mock(),
            backend_model_resolver=Mock(),
            failover_planner=Mock(),
            backend_completion_flow=Mock(),
        )

        # Test that delegation works
        backend_result = backend_service._apply_model_aliases(
            "claude-3-sonnet-20240229"
        )
        resolver_result = resolver.resolve("claude-3-sonnet-20240229")

        assert backend_result == resolver_result == "gemini-oauth-plan:gemini-1.5-flash"

    def test_backend_service_with_capture_groups(self) -> None:
        """Test BackendService delegation with capture group patterns."""
        from src.core.config.app_config import (
            AppConfig,
            BackendSettings,
            ModelAliasRule,
        )
        from src.core.services.backend_service import BackendService

        config = AppConfig(
            backends=BackendSettings(default_backend="openai"),
            model_aliases=[
                ModelAliasRule(
                    pattern="^gpt-(.*)",
                    replacement="openrouter:openai/gpt-\\1",
                ),
            ],
        )

        resolver = ModelAliasResolver(config=config)

        backend_service = BackendService(
            factory=Mock(),
            rate_limiter=Mock(),
            config=config,
            session_service=Mock(),
            app_state=Mock(),
            backend_config_provider=Mock(),
            stream_formatting_service=Mock(),
            usage_tracking_wrapper=Mock(),
            model_alias_resolver=resolver,
            exception_normalizer=Mock(),
            backend_lifecycle_manager=Mock(),
            planning_phase_manager=Mock(),
            reasoning_config_applicator=Mock(),
            uri_parameter_applicator=Mock(),
            stream_session_id_resolver=Mock(),
            backend_model_resolver=Mock(),
            failover_planner=Mock(),
            backend_completion_flow=Mock(),
        )

        backend_result = backend_service._apply_model_aliases("gpt-4o-mini")
        resolver_result = resolver.resolve("gpt-4o-mini")

        assert backend_result == resolver_result == "openrouter:openai/gpt-4o-mini"

    def test_backend_service_no_match_returns_original(self) -> None:
        """Test BackendService delegation when no patterns match."""
        from src.core.config.app_config import (
            AppConfig,
            BackendSettings,
            ModelAliasRule,
        )
        from src.core.services.backend_service import BackendService

        config = AppConfig(
            backends=BackendSettings(default_backend="openai"),
            model_aliases=[
                ModelAliasRule(
                    pattern="^special-.*$",
                    replacement="replaced",
                ),
            ],
        )

        resolver = ModelAliasResolver(config=config)

        backend_service = BackendService(
            factory=Mock(),
            rate_limiter=Mock(),
            config=config,
            session_service=Mock(),
            app_state=Mock(),
            backend_config_provider=Mock(),
            stream_formatting_service=Mock(),
            usage_tracking_wrapper=Mock(),
            model_alias_resolver=resolver,
            exception_normalizer=Mock(),
            backend_lifecycle_manager=Mock(),
            planning_phase_manager=Mock(),
            reasoning_config_applicator=Mock(),
            uri_parameter_applicator=Mock(),
            stream_session_id_resolver=Mock(),
            backend_model_resolver=Mock(),
            failover_planner=Mock(),
            backend_completion_flow=Mock(),
        )

        backend_result = backend_service._apply_model_aliases("normal-model")
        resolver_result = resolver.resolve("normal-model")

        assert backend_result == resolver_result == "normal-model"

    def test_backend_service_empty_aliases_returns_original(self) -> None:
        """Test BackendService delegation with empty alias list."""
        from src.core.config.app_config import AppConfig, BackendSettings
        from src.core.services.backend_service import BackendService

        config = AppConfig(
            backends=BackendSettings(default_backend="openai"),
            model_aliases=[],
        )

        resolver = ModelAliasResolver(config=config)

        backend_service = BackendService(
            factory=Mock(),
            rate_limiter=Mock(),
            config=config,
            session_service=Mock(),
            app_state=Mock(),
            backend_config_provider=Mock(),
            stream_formatting_service=Mock(),
            usage_tracking_wrapper=Mock(),
            model_alias_resolver=resolver,
            exception_normalizer=Mock(),
            backend_lifecycle_manager=Mock(),
            planning_phase_manager=Mock(),
            reasoning_config_applicator=Mock(),
            uri_parameter_applicator=Mock(),
            stream_session_id_resolver=Mock(),
            backend_model_resolver=Mock(),
            failover_planner=Mock(),
            backend_completion_flow=Mock(),
        )

        backend_result = backend_service._apply_model_aliases("my-model")
        resolver_result = resolver.resolve("my-model")

        assert backend_result == resolver_result == "my-model"
