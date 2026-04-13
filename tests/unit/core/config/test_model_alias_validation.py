"""
Unit tests for validate_model_aliases startup validation.

Tests cover:
- Valid alias replacements (single route, failover, weighted).
- Invalid regex patterns.
- Invalid composite syntax (mixed operators, empty branches).
- Invalid explicit leaf segments (empty backend/model).
- Unknown backend names in composite branches.
- URI params in leaf selectors are accepted.
"""

from __future__ import annotations

import importlib

import pytest
from src.core.common.exceptions import ConfigurationError
from src.core.config.app_config import AppConfig
from src.core.config.models.backends import BackendSettings
from src.core.config.models.rewriting import ModelAliasRule
from src.core.config.semantic_validation import (
    validate_model_aliases,
    warn_if_alias_references_without_rules,
)


class TestValidateModelAliases:
    """Test suite for validate_model_aliases function."""

    @pytest.fixture(autouse=True)
    def setup_connectors(self):
        importlib.import_module("src.connectors")
        yield

    def test_no_model_aliases_passes(self):
        config = AppConfig()
        validate_model_aliases(config)

    def test_valid_single_explicit_route_passes(self):
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="^my-alias$",
                    replacement="openai:gpt-4o",
                ),
            ],
        )
        validate_model_aliases(config)

    def test_valid_failover_alias_passes(self):
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="^failover-alias$",
                    replacement="openai:gpt-4o|anthropic:claude-3-5-sonnet",
                ),
            ],
        )
        validate_model_aliases(config)

    def test_valid_weighted_alias_passes(self):
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="^weighted-alias$",
                    replacement="[weight=3]openai:gpt-4o^[weight=1]anthropic:claude-3-haiku",
                ),
            ],
        )
        validate_model_aliases(config)

    def test_valid_failover_alias_like_configtest1(self):
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="^alias:minimax$",
                    replacement="ollama:minimax-m2.7:cloud|opencode-go:minimax-m2.7|opencode-zen:minimax-m2.5-free",
                ),
            ],
        )
        config.backends = BackendSettings()
        validate_model_aliases(config)

    def test_valid_alias_with_uri_params_passes(self):
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="^alias-params$",
                    replacement="openai:gpt-4?temperature=0.5&max_tokens=100",
                ),
            ],
        )
        validate_model_aliases(config)

    def test_valid_failover_alias_with_uri_params_passes(self):
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="^failover-params$",
                    replacement="openai:gpt-4?temperature=0.1|anthropic:claude-3-5-sonnet?temperature=0.8",
                ),
            ],
        )
        validate_model_aliases(config)

    def test_invalid_regex_pattern_raises(self):
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="[invalid(regex",
                    replacement="openai:gpt-4",
                ),
            ],
        )
        with pytest.raises(ConfigurationError) as exc_info:
            validate_model_aliases(config)

        assert exc_info.value.details.get("error_code") == "invalid_alias_regex"
        assert "[invalid(regex" in exc_info.value.message

    def test_empty_pattern_raises(self):
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(pattern="", replacement="openai:gpt-4"),
            ],
        )
        with pytest.raises(ConfigurationError) as exc_info:
            validate_model_aliases(config)

        assert exc_info.value.details.get("error_code") == "invalid_alias_pattern"

    def test_empty_replacement_raises(self):
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(pattern="^test$", replacement=""),
            ],
        )
        with pytest.raises(ConfigurationError) as exc_info:
            validate_model_aliases(config)

        assert exc_info.value.details.get("error_code") == "invalid_alias_replacement"

    def test_mixed_operators_raises(self):
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="^mixed$",
                    replacement="openai:gpt-4|anthropic:claude-3^openrouter:gpt-4o",
                ),
            ],
        )
        with pytest.raises(ConfigurationError) as exc_info:
            validate_model_aliases(config)

        assert (
            exc_info.value.details.get("error_code")
            == "invalid_alias_replacement_syntax"
        )

    def test_mixed_weighted_alias_is_normalized_and_passes(self):
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="^alias:gpt-5.3-codex-mixed$",
                    replacement=(
                        "openai-codex:gpt-5.3-codex?reasoning_effort=high"
                        "^[weight=4]openai-codex:gpt-5.3-codex?reasoning_effort=low"
                        "|[weight=2]openai-codex:gpt-5.3-codex?reasoning_effort=medium"
                    ),
                ),
            ],
        )

        validate_model_aliases(config)

        assert config.model_aliases[0].replacement == (
            "[weight=1]openai-codex:gpt-5.3-codex?reasoning_effort=high"
            "^[weight=4]openai-codex:gpt-5.3-codex?reasoning_effort=low"
            "^[weight=2]openai-codex:gpt-5.3-codex?reasoning_effort=medium"
        )

    def test_empty_branch_in_failover_raises(self):
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="^empty-branch$",
                    replacement="openai:gpt-4||anthropic:claude-3",
                ),
            ],
        )
        with pytest.raises(ConfigurationError) as exc_info:
            validate_model_aliases(config)

        assert (
            exc_info.value.details.get("error_code")
            == "invalid_alias_replacement_syntax"
        )

    def test_leading_weighted_separator_caret_raises_clear_error(self):
        """Leading '^' creates an empty branch; surface a dedicated message."""
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="^alias:oss-code-medium$",
                    replacement=(
                        "^[first]zai-coding-plan:glm-5.1"
                        "^[weight=4]qwen-oauth:qwen/coder-model"
                        "^[weight=2]opencode-go:opencode-go/mimo-v2-pro"
                    ),
                ),
            ],
        )
        with pytest.raises(ConfigurationError) as exc_info:
            validate_model_aliases(config)

        assert (
            exc_info.value.details.get("error_code")
            == "invalid_alias_replacement_leading_weighted_separator"
        )
        assert "starts with '^'" in exc_info.value.message
        assert (
            exc_info.value.details.get("reason") == "leading_caret_weighted_separator"
        )

    def test_leading_whitespace_before_caret_raises_same_error(self):
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="^x$",
                    replacement="  ^openai:gpt-4o^anthropic:claude-3-5-sonnet",
                ),
            ],
        )
        with pytest.raises(ConfigurationError) as exc_info:
            validate_model_aliases(config)

        assert (
            exc_info.value.details.get("error_code")
            == "invalid_alias_replacement_leading_weighted_separator"
        )

    def test_unknown_backend_raises(self):
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="^unknown-backend$",
                    replacement="nonexistent-backend:gpt-4|openai:gpt-4o",
                ),
            ],
        )
        with pytest.raises(ConfigurationError) as exc_info:
            validate_model_aliases(config)

        assert exc_info.value.details.get("error_code") == "unknown_alias_backend"
        assert "nonexistent-backend" in exc_info.value.message
        assert "available_backends" in exc_info.value.details

    def test_empty_backend_name_raises(self):
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="^empty-backend$",
                    replacement=":gpt-4",
                ),
            ],
        )
        with pytest.raises(ConfigurationError) as exc_info:
            validate_model_aliases(config)

        assert (
            exc_info.value.details.get("error_code")
            == "invalid_alias_replacement_syntax"
        )

    def test_empty_model_name_raises(self):
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="^empty-model$",
                    replacement="openai:",
                ),
            ],
        )
        with pytest.raises(ConfigurationError) as exc_info:
            validate_model_aliases(config)

        assert (
            exc_info.value.details.get("error_code")
            == "invalid_alias_replacement_syntax"
        )

    def test_model_only_leaf_passes_without_backend_validation(self):
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="^model-only$",
                    replacement="gpt-4o|claude-3-5-sonnet",
                ),
            ],
        )
        validate_model_aliases(config)

    def test_alias_error_contains_index_and_pattern(self):
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="^ok-alias$",
                    replacement="openai:gpt-4",
                ),
                ModelAliasRule(
                    pattern="[bad",
                    replacement="anthropic:claude-3",
                ),
            ],
        )
        with pytest.raises(ConfigurationError) as exc_info:
            validate_model_aliases(config)

        assert exc_info.value.details.get("alias_index") == 1
        assert exc_info.value.details.get("alias_pattern") == "[bad"

    def test_unknown_backend_error_contains_replacement_and_branch(self):
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="^test$",
                    replacement="bad-backend:model",
                ),
            ],
        )
        with pytest.raises(ConfigurationError) as exc_info:
            validate_model_aliases(config)

        details = exc_info.value.details
        assert details.get("replacement") == "bad-backend:model"
        assert details.get("failing_branch") == "bad-backend:model"
        assert details.get("invalid_backend") == "bad-backend"


class TestWarnIfAliasReferencesWithoutRules:
    """Test suite for warn_if_alias_references_without_rules startup warning."""

    def test_no_warning_when_aliases_populated(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        session = importlib.import_module("src.core.config.models.session")
        config = AppConfig(
            session=session.SessionConfig(quality_verifier_model="alias:verifier"),
            model_aliases=[
                ModelAliasRule(
                    pattern=r"^alias:verifier$", replacement="openai:gpt-4o"
                ),
            ],
        )
        with caplog.at_level("WARNING"):
            warn_if_alias_references_without_rules(config)
        assert not any("alias:/auto: selectors" in m for m in caplog.messages)

    def test_no_warning_when_no_alias_selectors(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        session = importlib.import_module("src.core.config.models.session")
        config = AppConfig(
            session=session.SessionConfig(quality_verifier_model="openai:gpt-4"),
            model_aliases=[],
        )
        with caplog.at_level("WARNING"):
            warn_if_alias_references_without_rules(config)
        assert not any("alias:/auto: selectors" in m for m in caplog.messages)

    def test_warns_on_quality_verifier_alias_selector(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        session = importlib.import_module("src.core.config.models.session")
        config = AppConfig(
            session=session.SessionConfig(quality_verifier_model="alias:verifier"),
            model_aliases=[],
        )
        with caplog.at_level("WARNING"):
            warn_if_alias_references_without_rules(config)
        assert any("alias:/auto: selectors" in m for m in caplog.messages)
        assert any(
            "quality_verifier_model='alias:verifier'" in m for m in caplog.messages
        )
        assert any("--config" in m for m in caplog.messages)

    def test_warns_on_auto_selector(self, caplog: pytest.LogCaptureFixture) -> None:
        session = importlib.import_module("src.core.config.models.session")
        config = AppConfig(
            session=session.SessionConfig(quality_verifier_model="auto:verifier"),
            model_aliases=[],
        )
        with caplog.at_level("WARNING"):
            warn_if_alias_references_without_rules(config)
        assert any("alias:/auto: selectors" in m for m in caplog.messages)

    def test_warns_on_static_route_alias_selector(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        backends = importlib.import_module("src.core.config.models.backends")
        config = AppConfig(
            backends=backends.BackendSettings(
                default_backend="openai",
                static_route="alias:oss-code-medium",
            ),
            model_aliases=[],
        )
        with caplog.at_level("WARNING"):
            warn_if_alias_references_without_rules(config)
        assert any("static_route='alias:oss-code-medium'" in m for m in caplog.messages)
        assert any("--config" in m for m in caplog.messages)
