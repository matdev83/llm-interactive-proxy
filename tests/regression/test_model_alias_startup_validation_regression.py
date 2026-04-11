"""
Regression test for model-alias startup validation.

Original bug: YAML configs with complex alias replacements (failover, weighted,
URI params) were only validated for syntax, with no startup-time checking of
composite routing grammar or backend-name validity.  If a replacement string
was malformed or referenced a nonexistent backend, the server would start
normally and only fail later at request time.

Regression guard: any model alias with invalid composite syntax, invalid regex,
or unknown backend must cause startup to fail with ConfigurationError.
"""

from __future__ import annotations

import importlib

import pytest
from src.core.app.application_builder import ApplicationBuilder
from src.core.common.exceptions import ConfigurationError
from src.core.config.app_config import AppConfig
from src.core.config.models.backends import BackendSettings
from src.core.config.models.rewriting import ModelAliasRule
from src.core.config.semantic_validation import (
    validate_model_aliases,
    warn_if_alias_references_without_rules,
)


class TestAliasSelectorStartupWarning:
    """Guard against silent startup when alias:/auto: selectors have no rules."""

    @pytest.fixture(autouse=True)
    def setup_connectors(self):
        importlib.import_module("src.connectors")
        yield

    def test_warns_on_quality_verifier_alias_without_rules(
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

    def test_warns_on_auto_selector_without_rules(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        session = importlib.import_module("src.core.config.models.session")
        config = AppConfig(
            session=session.SessionConfig(quality_verifier_model="auto:reasoning"),
            model_aliases=[],
        )
        with caplog.at_level("WARNING"):
            warn_if_alias_references_without_rules(config)
        assert any("alias:/auto: selectors" in m for m in caplog.messages)
        assert any(
            "quality_verifier_model='auto:reasoning'" in m for m in caplog.messages
        )

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


class TestModelAliasStartupValidationRegression:
    """Guard against silent startup on bad alias replacements."""

    @pytest.fixture(autouse=True)
    def setup_connectors(self):
        importlib.import_module("src.connectors")
        yield

    # -- Syntax / grammar regression guards --

    def test_composite_syntax_error_in_alias_fails_startup(self) -> None:
        """Mixed | and ^ in one replacement must abort startup."""
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="^broken$",
                    replacement="openai:gpt-4|anthropic:claude-3^gemini:flash",
                ),
            ],
        )
        with pytest.raises(ConfigurationError) as exc_info:
            validate_model_aliases(config)

        assert (
            exc_info.value.details.get("error_code")
            == "invalid_alias_replacement_syntax"
        )
        assert "openai:gpt-4|anthropic:claude-3^gemini:flash" in exc_info.value.message

    def test_empty_branch_in_composite_fails_startup(self) -> None:
        """Double separator || or ^^ must abort startup."""
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

    def test_invalid_regex_in_alias_fails_startup(self) -> None:
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="[unclosed-bracket",
                    replacement="openai:gpt-4",
                ),
            ],
        )
        with pytest.raises(ConfigurationError) as exc_info:
            validate_model_aliases(config)

        assert exc_info.value.details.get("error_code") == "invalid_alias_regex"

    def test_empty_replacement_fails_startup(self) -> None:
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(pattern="^alias$", replacement=""),
            ],
        )
        with pytest.raises(ConfigurationError) as exc_info:
            validate_model_aliases(config)

        assert exc_info.value.details.get("error_code") == "invalid_alias_replacement"

    def test_empty_pattern_fails_startup(self) -> None:
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(pattern="", replacement="openai:gpt-4"),
            ],
        )
        with pytest.raises(ConfigurationError) as exc_info:
            validate_model_aliases(config)

        assert exc_info.value.details.get("error_code") == "invalid_alias_pattern"

    # -- Backend-name regression guards --

    def test_unknown_backend_in_alias_fails_startup(self) -> None:
        """A replacement referencing a backend not in the registry must abort."""
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="^bad-backend$",
                    replacement="unknown-provider:gpt-4",
                ),
            ],
        )
        with pytest.raises(ConfigurationError) as exc_info:
            validate_model_aliases(config)

        assert exc_info.value.details.get("error_code") == "unknown_alias_backend"
        assert "unknown-provider" in exc_info.value.message
        assert "available_backends" in exc_info.value.details

    def test_unknown_backend_in_one_branch_of_failover_fails_startup(self) -> None:
        """Even if other branches are valid, one bad backend must fail."""
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="^partial-bad$",
                    replacement="openai:gpt-4|unknown-backend:claude-3",
                ),
            ],
        )
        with pytest.raises(ConfigurationError) as exc_info:
            validate_model_aliases(config)

        assert exc_info.value.details.get("error_code") == "unknown_alias_backend"

    def test_empty_backend_segment_in_explicit_selector_fails_startup(self) -> None:
        """`:model` without a backend name must abort."""
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(pattern="^colon-prefix$", replacement=":gpt-4"),
            ],
        )
        with pytest.raises(ConfigurationError) as exc_info:
            validate_model_aliases(config)

        assert (
            exc_info.value.details.get("error_code")
            == "invalid_alias_replacement_syntax"
        )

    def test_empty_model_segment_in_explicit_selector_fails_startup(self) -> None:
        """`backend:` without a model name must abort."""
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(pattern="^colon-suffix$", replacement="openai:"),
            ],
        )
        with pytest.raises(ConfigurationError) as exc_info:
            validate_model_aliases(config)

        assert (
            exc_info.value.details.get("error_code")
            == "invalid_alias_replacement_syntax"
        )

    # -- Positive: valid complex replacements pass --

    def test_valid_weighted_alias_with_uri_params_passes(self) -> None:
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="^weighted-params$",
                    replacement="[weight=3]openai:gpt-4?temperature=0.5^[weight=1]anthropic:claude-3?temperature=0.7",
                ),
            ],
        )
        validate_model_aliases(config)

    def test_valid_failover_alias_like_configtest1_passes(self) -> None:
        """Matches the pattern used in config/configtest1.yaml."""
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="^alias:minimax$",
                    replacement=(
                        "ollama:minimax-m2.7:cloud"
                        "|opencode-go:minimax-m2.7"
                        "|opencode-zen:minimax-m2.5-free"
                    ),
                ),
            ],
        )
        config.backends = BackendSettings()
        validate_model_aliases(config)

    # -- Builder-level regression: startup must reject bad aliases --

    @pytest.mark.asyncio
    async def test_builder_aborts_on_bad_alias(self) -> None:
        """ApplicationBuilder.build() must raise through the call stack."""
        from src.core.app.stages.base import InitializationStage
        from src.core.di.container import ServiceCollection

        class DummyStage(InitializationStage):
            @property
            def name(self) -> str:
                return "dummy"

            def get_dependencies(self) -> list[str]:
                return []

            def get_description(self) -> str:
                return "dummy"

            async def validate(
                self, services: ServiceCollection, config: AppConfig
            ) -> bool:
                return True

            async def execute(
                self, services: ServiceCollection, config: AppConfig
            ) -> None:
                pass

        builder = ApplicationBuilder()
        builder.add_stage(DummyStage())
        config = AppConfig(
            model_aliases=[
                ModelAliasRule(
                    pattern="^bad$",
                    replacement="nonexistent-backend:gpt-4",
                ),
            ],
        )

        with pytest.raises(ConfigurationError) as exc_info:
            await builder.build(config)

        assert exc_info.value.details.get("error_code") == "unknown_alias_backend"
