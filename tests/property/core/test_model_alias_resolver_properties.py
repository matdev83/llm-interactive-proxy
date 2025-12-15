"""Property-based tests for ModelAliasResolver.

Validates:
- Property 5: Model Alias Round-Trip (Requirements 7.1, 7.2)
- Property 6: Alias Graceful Degradation (Requirements 7.3, 7.4)
"""

from __future__ import annotations

from unittest.mock import MagicMock

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
    """Ensure ModelAliasResolver matches BackendService._apply_model_aliases behavior."""

    def test_simple_replacement_matches_backend_service(self) -> None:
        """Simple pattern replacement should match BackendService behavior."""
        from unittest.mock import Mock

        from src.core.config.app_config import (
            AppConfig,
            BackendSettings,
            ModelAliasRule,
        )
        from src.core.services.backend_service import BackendService

        config = AppConfig(
            backends=BackendSettings(default_backend="openai"),
            model_aliases=[
                ModelAliasRule(pattern="^claude-3$", replacement="anthropic:claude-3"),
            ],
        )

        # BackendService result
        backend_service = BackendService(
            factory=Mock(),
            rate_limiter=Mock(),
            config=config,
            session_service=Mock(),
            app_state=Mock(),
        )
        backend_result = backend_service._apply_model_aliases("claude-3")

        # ModelAliasResolver result
        resolver = ModelAliasResolver(config=config)
        resolver_result = resolver.resolve("claude-3")

        assert backend_result == resolver_result == "anthropic:claude-3"

    def test_capture_group_expansion_matches_backend_service(self) -> None:
        """Capture group expansion should match BackendService behavior."""
        from unittest.mock import Mock

        from src.core.config.app_config import (
            AppConfig,
            BackendSettings,
            ModelAliasRule,
        )
        from src.core.services.backend_service import BackendService

        config = AppConfig(
            backends=BackendSettings(default_backend="openai"),
            model_aliases=[
                ModelAliasRule(pattern="^gpt-(.*)", replacement="openai:gpt-\\1"),
            ],
        )

        backend_service = BackendService(
            factory=Mock(),
            rate_limiter=Mock(),
            config=config,
            session_service=Mock(),
            app_state=Mock(),
        )
        backend_result = backend_service._apply_model_aliases("gpt-4o-mini")

        resolver = ModelAliasResolver(config=config)
        resolver_result = resolver.resolve("gpt-4o-mini")

        assert backend_result == resolver_result == "openai:gpt-4o-mini"

    def test_no_match_returns_original(self) -> None:
        """Non-matching patterns should return original in both implementations."""
        from unittest.mock import Mock

        from src.core.config.app_config import (
            AppConfig,
            BackendSettings,
            ModelAliasRule,
        )
        from src.core.services.backend_service import BackendService

        config = AppConfig(
            backends=BackendSettings(default_backend="openai"),
            model_aliases=[
                ModelAliasRule(pattern="^special-.*$", replacement="replaced"),
            ],
        )

        backend_service = BackendService(
            factory=Mock(),
            rate_limiter=Mock(),
            config=config,
            session_service=Mock(),
            app_state=Mock(),
        )
        backend_result = backend_service._apply_model_aliases("normal-model")

        resolver = ModelAliasResolver(config=config)
        resolver_result = resolver.resolve("normal-model")

        assert backend_result == resolver_result == "normal-model"
