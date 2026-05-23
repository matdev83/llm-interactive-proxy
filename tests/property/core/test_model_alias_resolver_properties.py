"""Property-based tests for ModelAliasResolver.

Validates:
- Property 5: Model Alias Round-Trip (Requirements 7.1, 7.2)
- Property 6: Alias Graceful Degradation (Requirements 7.3, 7.4)
"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock

from hypothesis import assume, given, settings
from hypothesis import strategies as st
from src.core.services.model_alias_resolver import ModelAliasResolver


def mock_alias_rule(pattern: str, replacement: str) -> MagicMock:
    """Create a mock alias rule with pattern and replacement."""
    rule = MagicMock()
    rule.pattern = pattern
    rule.replacement = replacement
    return rule


def mock_config_with_aliases(aliases: list) -> MagicMock:
    """Create a mock config with model aliases."""
    config = MagicMock()
    config.model_aliases = aliases
    return config


class TestModelAliasRoundTripProperty:
    """Property 5: Model Alias Round-Trip (Requirements 7.1, 7.2)."""

    @given(
        model_name=st.text(
            min_size=1, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_"
        )
    )
    @settings(max_examples=50)
    def test_no_aliases_returns_original(self, model_name: str) -> None:
        """With no aliases configured, model name should pass through unchanged."""
        config = mock_config_with_aliases([])
        resolver = ModelAliasResolver(config=config)

        result = resolver.resolve(model_name)

        assert result == model_name

    @given(
        model_name=st.text(
            min_size=1, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_"
        )
    )
    @settings(max_examples=50)
    def test_non_matching_alias_returns_original(self, model_name: str) -> None:
        """Non-matching alias patterns should return original model name."""
        assume(not model_name.startswith("special-prefix"))

        config = mock_config_with_aliases(
            [mock_alias_rule("^special-prefix-.*$", "replaced-model")]
        )
        resolver = ModelAliasResolver(config=config)

        result = resolver.resolve(model_name)

        assert result == model_name

    @given(
        suffix=st.text(
            min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz0123456789"
        )
    )
    @settings(max_examples=50)
    def test_matching_alias_applies_replacement(self, suffix: str) -> None:
        """Matching alias patterns should apply the replacement."""
        model_name = f"gpt-{suffix}"

        config = mock_config_with_aliases(
            [mock_alias_rule("^gpt-(.*)", "openai-gpt-\\1")]
        )
        resolver = ModelAliasResolver(config=config)

        result = resolver.resolve(model_name)

        assert result == f"openai-gpt-{suffix}"

    @given(
        model_name=st.text(
            min_size=1, max_size=30, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-"
        )
    )
    @settings(max_examples=30)
    def test_first_match_wins(self, model_name: str) -> None:
        """First matching alias should be applied, subsequent ones ignored."""
        config = mock_config_with_aliases(
            [
                mock_alias_rule("^.*$", "first-match"),
                mock_alias_rule("^.*$", "second-match"),
            ]
        )
        resolver = ModelAliasResolver(config=config)

        result = resolver.resolve(model_name)

        assert result == "first-match"

    @given(
        prefix=st.text(min_size=1, max_size=10, alphabet="abcdefghijklmnopqrstuvwxyz"),
        suffix=st.text(min_size=1, max_size=10, alphabet="abcdefghijklmnopqrstuvwxyz"),
    )
    @settings(max_examples=30)
    def test_capture_groups_preserved(self, prefix: str, suffix: str) -> None:
        """Capture groups in replacement should be correctly expanded."""
        model_name = f"{prefix}-model-{suffix}"

        config = mock_config_with_aliases(
            [mock_alias_rule("^(.*)-model-(.*)$", "new-\\1-and-\\2")]
        )
        resolver = ModelAliasResolver(config=config)

        result = resolver.resolve(model_name)

        assert result == f"new-{prefix}-and-{suffix}"


class TestAliasGracefulDegradationProperty:
    """Property 6: Alias Graceful Degradation (Requirements 7.3, 7.4)."""

    @given(
        model_name=st.text(
            min_size=1, max_size=30, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-"
        )
    )
    @settings(max_examples=30)
    def test_invalid_regex_pattern_skipped(self, model_name: str) -> None:
        """Invalid regex patterns should be skipped without throwing."""
        config = mock_config_with_aliases(
            [
                mock_alias_rule("[invalid(regex", "replacement"),  # Invalid regex
                mock_alias_rule("^valid-pattern$", "valid-replacement"),
            ]
        )
        resolver = ModelAliasResolver(config=config)

        # Should not raise, should return original or match valid pattern
        result = resolver.resolve(model_name)

        if model_name == "valid-pattern":
            assert result == "valid-replacement"
        else:
            assert result == model_name

    @given(
        model_name=st.text(
            min_size=1, max_size=30, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-"
        )
    )
    @settings(max_examples=30)
    def test_none_config_returns_original(self, model_name: str) -> None:
        """None config should return original model name."""
        resolver = ModelAliasResolver(config=None)

        result = resolver.resolve(model_name)

        assert result == model_name

    @given(
        model_name=st.text(
            min_size=1, max_size=30, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-"
        )
    )
    @settings(max_examples=30)
    def test_alias_with_none_pattern_skipped(self, model_name: str) -> None:
        """Aliases with None pattern should be skipped."""
        alias = MagicMock()
        alias.pattern = None
        alias.replacement = "replacement"

        config = mock_config_with_aliases([alias])
        resolver = ModelAliasResolver(config=config)

        result = resolver.resolve(model_name)

        assert result == model_name

    @given(
        model_name=st.text(
            min_size=1, max_size=30, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-"
        )
    )
    @settings(max_examples=30)
    def test_alias_with_none_replacement_skipped(self, model_name: str) -> None:
        """Aliases with None replacement should be skipped."""
        alias = MagicMock()
        alias.pattern = "^.*$"
        alias.replacement = None

        config = mock_config_with_aliases([alias])
        resolver = ModelAliasResolver(config=config)

        result = resolver.resolve(model_name)

        assert result == model_name

    @given(
        model_name=st.text(
            min_size=1, max_size=30, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-"
        )
    )
    @settings(max_examples=30)
    def test_mock_alias_raises_attribute_error_skipped(self, model_name: str) -> None:
        """Aliases that raise AttributeError should be skipped."""
        alias = MagicMock()
        alias.pattern = property(
            lambda self: (_ for _ in ()).throw(AttributeError("mock"))
        )

        config = mock_config_with_aliases([alias])
        resolver = ModelAliasResolver(config=config)

        # Should not raise
        result = resolver.resolve(model_name)
        # Result will be original since pattern access fails
        assert isinstance(result, str)


class TestEquivalenceWithBackendService:
    """Property-based integration tests verifying BackendService delegates correctly to ModelAliasResolver.

    After Phase 4 refactoring, BackendService delegates model alias resolution to
    ModelAliasResolver. These tests verify that the delegation works correctly
    and produces equivalent results using property-based testing.
    """

    @given(
        model_name=st.text(
            min_size=1, max_size=30, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-"
        )
    )
    @settings(max_examples=20, deadline=None)
    def test_backend_service_delegation_property(self, model_name: str) -> None:
        """Property test: BackendService delegation should be equivalent to direct ModelAliasResolver usage."""
        from src.core.config.app_config import (
            AppConfig,
            BackendSettings,
            ModelAliasRule,
        )
        from src.core.services.backend_service import BackendService

        config = AppConfig(
            backends=BackendSettings(default_backend="openai"),
            model_aliases=[
                ModelAliasRule(pattern="^claude-.*$", replacement="anthropic:claude"),
                ModelAliasRule(pattern="^gpt-(.*)", replacement="openai:gpt-\\1"),
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

        backend_result = backend_service._apply_model_aliases(model_name)
        resolver_result = resolver.resolve(model_name)

        # Results should be identical
        assert backend_result == resolver_result

    @given(
        pattern=st.text(
            min_size=3,
            max_size=20,
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789-.*^$",
        ),
        replacement=st.text(
            min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-\\"
        ),
        model_name=st.text(
            min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-"
        ),
    )
    @settings(max_examples=10, deadline=None)
    def test_delegation_with_various_patterns(
        self, pattern: str, replacement: str, model_name: str
    ) -> None:
        """Property test: Delegation should work correctly with various regex patterns."""
        from src.core.config.app_config import (
            AppConfig,
            BackendSettings,
            ModelAliasRule,
        )
        from src.core.services.backend_service import BackendService

        # Skip patterns that are definitely invalid regex
        assume(not pattern.startswith("[") or pattern.endswith("]"))

        try:
            # Test if pattern is valid regex
            import re

            re.compile(pattern)

            config = AppConfig(
                backends=BackendSettings(default_backend="openai"),
                model_aliases=[
                    ModelAliasRule(pattern=pattern, replacement=replacement),
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

            backend_result = backend_service._apply_model_aliases(model_name)
            resolver_result = resolver.resolve(model_name)

            # Results should be identical
            assert backend_result == resolver_result

        except re.error:
            # Skip invalid regex patterns
            pass

    @given(aliases_count=st.integers(min_value=0, max_value=5))
    @settings(max_examples=5, deadline=None)
    def test_delegation_with_multiple_aliases(self, aliases_count: int) -> None:
        """Property test: Delegation should work correctly with multiple alias rules."""
        from src.core.config.app_config import (
            AppConfig,
            BackendSettings,
            ModelAliasRule,
        )
        from src.core.services.backend_service import BackendService

        # Generate multiple alias rules
        aliases = []
        for i in range(aliases_count):
            aliases.append(
                ModelAliasRule(
                    pattern=f"^pattern-{i}-.*$", replacement=f"replacement-{i}"
                )
            )

        config = AppConfig(
            backends=BackendSettings(default_backend="openai"),
            model_aliases=aliases,
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

        test_models = [
            "pattern-0-test",
            "pattern-1-test",
            "unrelated-model",
            "pattern-3-test",
        ]

        for model in test_models:
            backend_result = backend_service._apply_model_aliases(model)
            resolver_result = resolver.resolve(model)

            # Results should be identical for all test models
            assert backend_result == resolver_result
