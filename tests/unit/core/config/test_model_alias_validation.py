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
from src.core.config.semantic_validation import validate_model_aliases


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
